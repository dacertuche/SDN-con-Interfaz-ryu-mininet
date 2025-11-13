#!/usr/bin/env python3
# Proactive Routing for NSFNET (14/21) – Ryu (OpenFlow 1.3)
# Modos: "hops" (no ponderado) | "distrak" (peso = 1/Bw)
#
# Requiere: pip install networkx
# Ejecutar: ryu-manager --observe-links ryu_app.py
#
# Extensión: Monitoreo de estadísticas (throughput, packet loss, port stats)

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.topology import event, api as topo_api
from ryu.app.wsgi import WSGIApplication, ControllerBase, route, Response
from ryu.lib import hub

import json
import networkx as nx
from collections import defaultdict
import time

API_INSTANCE = 'PR_APP_INSTANCE'
NUM_HOSTS = 14  # h1..h14 -> 10.0.0.1..10.0.0.14

def ip_of(i: int) -> str:
    return f"10.0.0.{i}"

def undirected_key(a, b):
    return (a, b) if a < b else (b, a)

class ProactiveRouting(app_manager.RyuApp):
    _CONTEXTS = { 'wsgi': WSGIApplication }
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        wsgi = kwargs['wsgi']
        wsgi.register(RestAPI, {API_INSTANCE: self})

        self.mode = 'hops'              # "hops" | "distrak"
        self.G = nx.Graph()             # grafo de switches
        self.adj = {}                   # (u,v) -> out_port (desde u hacia v)
        self.datapaths = {}             # dpid -> datapath

        # Conjuntos de puertos
        self.sw_all_ports  = defaultdict(set)  # dpid -> {puertos válidos (<OFPP_MAX)}
        self.sw_link_ports = defaultdict(set)  # dpid -> {puertos usados en enlaces s-s}
        self.host_port     = {}                # dpid -> puerto hacia host detectado

        # Tabla de BW (Mbps) idéntica a la del Mininet topo_nsfnet.py
        self.link_bw = {
            undirected_key(1,2):50, undirected_key(1,5):30,
            undirected_key(2,3):20, undirected_key(2,6):40,
            undirected_key(3,4):25, undirected_key(3,7):35,
            undirected_key(4,8):45, undirected_key(5,6):10,
            undirected_key(5,9):20, undirected_key(6,7):50,
            undirected_key(6,10):8, undirected_key(7,11):40,
            undirected_key(8,12):30, undirected_key(9,10):40,
            undirected_key(9,13):35, undirected_key(10,11):20,
            undirected_key(10,14):30, undirected_key(11,12):45,
            undirected_key(12,14):25, undirected_key(13,14):15,
            undirected_key(8,11):20,
        }
        self.default_bw = 10  # por si aparece un enlace no mapeado

        # ===== NUEVO: Estadísticas de monitoreo =====
        self.port_stats = {}  # dpid -> {port_no: {'tx_bytes', 'rx_bytes', 'tx_packets', ...}}
        self.port_stats_prev = {}  # Para calcular diferencias
        self.port_speed = {}  # dpid -> {port_no: speed_bps}
        self.flow_stats = {}  # dpid -> [flow entries]
        self.stats_timestamp = {}  # dpid -> timestamp de última actualización
        
        # Hilo para solicitar estadísticas periódicamente
        self.monitor_thread = hub.spawn(self._monitor_loop)

    # ============== Gestión de estados/DPs ==============

    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, CONFIG_DISPATCHER, DEAD_DISPATCHER])
    def _state_change(self, ev):
        dp = ev.datapath
        if ev.state in (MAIN_DISPATCHER, CONFIG_DISPATCHER):
            self.datapaths[dp.id] = dp
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(dp.id, None)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def _switch_features(self, ev):
        """Instala reglas base y pide descripción de puertos (PortDesc)."""
        dp = ev.msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        # (A) PUNT LLDP -> CONTROLLER (descubrimiento de enlaces con --observe-links)
        match_lldp = parser.OFPMatch(eth_type=0x88cc)
        actions_lldp = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        inst_lldp = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions_lldp)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=500,
                                      match=match_lldp, instructions=inst_lldp))

        # (B) TABLE-MISS: DROP (evita flooding)
        match_any = parser.OFPMatch()
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=0,
                                      match=match_any, instructions=[]))

        # (C) Solicitar descripción de puertos para autodetectar puertos host
        req = parser.OFPPortDescStatsRequest(dp, 0)
        dp.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def _port_desc_reply(self, ev):
        """Registra los puertos válidos del switch (excluye reservados)."""
        dp = ev.msg.datapath
        ofp = dp.ofproto
        ports = set()
        for p in ev.msg.body:
            if p.port_no < ofp.OFPP_MAX:  # ignora puertos reservados (LOCAL, etc.)
                ports.add(p.port_no)
        self.sw_all_ports[dp.id] = ports
        self.logger.info("s%d: puertos válidos %s", dp.id, sorted(list(ports)))
        # Tras tener puertos, intenta reconstruir y pushear
        self._rebuild_graph_and_push()

    # ============== Eventos de topología (LLDP) ==============

    @set_ev_cls(event.EventSwitchEnter)
    def _on_switch_enter(self, ev):
        self.logger.info("Switch enter -> reconstruir grafo + flujos")
        self._rebuild_graph_and_push()

    @set_ev_cls(event.EventLinkAdd)
    def _on_link_add(self, ev):
        self.logger.info("Link add -> reconstruir grafo + flujos")
        self._rebuild_graph_and_push()

    # ============== Núcleo: construir grafo y empujar flujos ==============

    def _install_base_rules(self, dp):
        """Reinstala reglas base (LLDP->CTRL y table-miss DROP) tras borrar todo."""
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        # LLDP punt to controller
        match_lldp = parser.OFPMatch(eth_type=0x88cc)
        actions_lldp = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        inst_lldp = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions_lldp)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=500,
                                      match=match_lldp, instructions=inst_lldp))

        # Table-miss drop
        match_any = parser.OFPMatch()
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=0,
                                      match=match_any, instructions=[]))

    def _rebuild_graph_and_push(self):
        """Reconstruye el grafo, deduce puertos host y reinstala flujos proactivos."""
        self._build_graph()
        if self.G.number_of_nodes() == 0:
            self.logger.warning("Grafo vacío (¿arrancaste con --observe-links y LLDP punt?)")
            return
        self._deduce_host_ports()
        self._clear_all_flows()
        self._install_all_destinations()

    def _build_graph(self):
        """Construye grafo y mapa de puertos de salida entre switches."""
        self.G.clear()
        self.adj.clear()
        self.sw_link_ports.clear()

        switches = topo_api.get_all_switch(self)
        links = topo_api.get_all_link(self)

        for sw in switches:
            self.G.add_node(sw.dp.id)

        for lk in links:
            u, v = lk.src.dpid, lk.dst.dpid
            # mapa de "siguiente salto"
            self.adj[(u, v)] = lk.src.port_no
            self.adj[(v, u)] = lk.dst.port_no

            # marca puertos usados por enlaces s-s
            self.sw_link_ports[u].add(lk.src.port_no)
            self.sw_link_ports[v].add(lk.dst.port_no)

            # peso/bw
            bw = self.link_bw.get(undirected_key(u, v), self.default_bw)
            weight = 1.0 / bw if self.mode == 'distrak' else 1.0
            self.G.add_edge(u, v, bw=bw, weight=weight)

        self.logger.info("Grafo listo: %d nodos, %d enlaces (modo=%s)",
                         self.G.number_of_nodes(), self.G.number_of_edges(), self.mode)

    def _deduce_host_ports(self):
        """Para cada switch, determina el puerto host = (todos) - (puertos de enlaces)."""
        self.host_port.clear()
        for dpid in self.G.nodes:
            allp  = self.sw_all_ports.get(dpid, set())
            linkp = self.sw_link_ports.get(dpid, set())
            cand = allp - linkp
            if len(cand) == 1:
                hp = next(iter(cand))
            elif len(cand) > 1:
                hp = min(cand)
                self.logger.warning("s%d: múltiples candidatos host-port %s -> uso %d", dpid, sorted(list(cand)), hp)
            else:
                hp = 1
                self.logger.warning("s%d: sin candidato claro a host-port -> asumo 1", dpid)
            self.host_port[dpid] = hp
            self.logger.info("s%d: host-port = %d", dpid, hp)

    def _clear_all_flows(self):
        """Borra flujos en todos los switches y reinstala reglas base."""
        for dpid, dp in self.datapaths.items():
            ofp = dp.ofproto
            parser = dp.ofproto_parser
            # Delete all
            mod = parser.OFPFlowMod(
                datapath=dp,
                command=ofp.OFPFC_DELETE,
                out_port=ofp.OFPP_ANY,
                out_group=ofp.OFPG_ANY
            )
            dp.send_msg(mod)
            # Base rules (LLDP -> CTRL, table-miss drop)
            self._install_base_rules(dp)

    def _install_all_destinations(self):
        """Para cada destino 10.0.0.j en s_j, instala rutas (IP+ARP) en todo el grafo."""
        for j in range(1, NUM_HOSTS + 1):
            dst_ip = ip_of(j)
            dst_sw = j  # sup: h_j en s_j
            if dst_sw not in self.G:
                self.logger.warning("s%d (destino de %s) no está en el grafo", dst_sw, dst_ip)
                continue
            self._install_tree_to_destination(dst_sw, dst_ip)
        self.logger.info("Flujos proactivos instalados para todos los destinos.")

    def _install_tree_to_destination(self, dst_sw: int, dst_ip: str):
        """Para cada switch u, instala salida hacia dst_ip por el siguiente salto hacia dst_sw.
           En dst_sw, la salida es el puerto de acceso al host (autodetectado)."""
        for u in self.G.nodes:
            # Determinar puerto de salida en u
            if u == dst_sw:
                out_port = self.host_port.get(dst_sw, 1)
            else:
                try:
                    path = nx.shortest_path(self.G, source=u, target=dst_sw, weight='weight')
                except nx.NetworkXNoPath:
                    self.logger.warning("No hay ruta s%d -> s%d para %s", u, dst_sw, dst_ip)
                    continue
                if len(path) < 2:
                    continue
                v = path[1]  # siguiente switch
                out_port = self.adj.get((u, v))
                if out_port is None:
                    self.logger.warning("Desconozco puerto s%d->s%d (dst %s)", u, v, dst_ip)
                    continue

            dp = self.datapaths.get(u)
            if not dp:
                continue

            parser = dp.ofproto_parser
            ofp = dp.ofproto

            actions = [parser.OFPActionOutput(out_port)]
            inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]

            # IPv4 hacia dst_ip
            match_ip = parser.OFPMatch(eth_type=0x0800, ipv4_dst=dst_ip)
            mod_ip = parser.OFPFlowMod(datapath=dp, priority=100, match=match_ip, instructions=inst)
            dp.send_msg(mod_ip)

            # ARP hacia dst_ip (tpa = target protocol address)
            match_arp = parser.OFPMatch(eth_type=0x0806, arp_tpa=dst_ip)
            mod_arp = parser.OFPFlowMod(datapath=dp, priority=100, match=match_arp, instructions=inst)
            dp.send_msg(mod_arp)

    # ============== NUEVO: Monitoreo de estadísticas ==============

    def _monitor_loop(self):
        """Hilo que solicita estadísticas cada 5 segundos."""
        while True:
            for dp in list(self.datapaths.values()):
                self._request_stats(dp)
            hub.sleep(5)

    def _request_stats(self, datapath):
        """Solicita estadísticas de puertos y flujos."""
        parser = datapath.ofproto_parser
        
        # Solicitar estadísticas de puertos
        req = parser.OFPPortStatsRequest(datapath, 0, datapath.ofproto.OFPP_ANY)
        datapath.send_msg(req)
        
        # Solicitar estadísticas de flujos
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply(self, ev):
        """Procesa estadísticas de puertos."""
        body = ev.msg.body
        dpid = ev.msg.datapath.id
        timestamp = time.time()
        
        if dpid not in self.port_stats:
            self.port_stats[dpid] = {}
            self.port_stats_prev[dpid] = {}
        
        for stat in body:
            port_no = stat.port_no
            
            # Guardar estadísticas anteriores
            if port_no in self.port_stats[dpid]:
                self.port_stats_prev[dpid][port_no] = self.port_stats[dpid][port_no].copy()
            
            # Actualizar estadísticas actuales
            self.port_stats[dpid][port_no] = {
                'rx_packets': stat.rx_packets,
                'tx_packets': stat.tx_packets,
                'rx_bytes': stat.rx_bytes,
                'tx_bytes': stat.tx_bytes,
                'rx_dropped': stat.rx_dropped,
                'tx_dropped': stat.tx_dropped,
                'rx_errors': stat.rx_errors,
                'tx_errors': stat.tx_errors,
                'timestamp': timestamp
            }
        
        self.stats_timestamp[dpid] = timestamp

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply(self, ev):
        """Procesa estadísticas de flujos."""
        body = ev.msg.body
        dpid = ev.msg.datapath.id
        
        flows = []
        for stat in body:
            flows.append({
                'priority': stat.priority,
                'match': str(stat.match),
                'duration_sec': stat.duration_sec,
                'packet_count': stat.packet_count,
                'byte_count': stat.byte_count
            })
        
        self.flow_stats[dpid] = flows

    def get_link_stats(self):
        """Calcula estadísticas de enlaces (throughput, packet loss)."""
        link_stats = []
        
        for (u, v) in self.adj.keys():
            if u > v:  # Evitar duplicados (solo procesar u < v)
                continue
            
            port_u = self.adj.get((u, v))
            port_v = self.adj.get((v, u))
            
            if not port_u or not port_v:
                continue
            
            # Obtener estadísticas de ambos puertos
            stats_u = self.port_stats.get(u, {}).get(port_u, {})
            stats_v = self.port_stats.get(v, {}).get(port_v, {})
            stats_u_prev = self.port_stats_prev.get(u, {}).get(port_u, {})
            stats_v_prev = self.port_stats_prev.get(v, {}).get(port_v, {})
            
            if not stats_u or not stats_v:
                continue
            
            # Calcular throughput (Mbps)
            time_diff = stats_u.get('timestamp', 0) - stats_u_prev.get('timestamp', 0)
            if time_diff > 0:
                # TX de u -> RX de v
                bytes_u_tx = stats_u.get('tx_bytes', 0) - stats_u_prev.get('tx_bytes', 0)
                bytes_v_rx = stats_v.get('rx_bytes', 0) - stats_v_prev.get('rx_bytes', 0)
                
                throughput_u_to_v = (bytes_u_tx * 8) / (time_diff * 1000000)  # Mbps
                throughput_v_to_u = (bytes_v_rx * 8) / (time_diff * 1000000)  # Mbps
                
                # Packet loss (diferencia entre TX y RX)
                packets_u_tx = stats_u.get('tx_packets', 0) - stats_u_prev.get('tx_packets', 0)
                packets_v_rx = stats_v.get('rx_packets', 0) - stats_v_prev.get('rx_packets', 0)
                
                packet_loss = max(0, packets_u_tx - packets_v_rx)
                loss_rate = (packet_loss / packets_u_tx * 100) if packets_u_tx > 0 else 0
            else:
                throughput_u_to_v = 0
                throughput_v_to_u = 0
                loss_rate = 0
            
            bw = self.link_bw.get(undirected_key(u, v), self.default_bw)
            
            link_stats.append({
                'src': u,
                'dst': v,
                'src_port': port_u,
                'dst_port': port_v,
                'bw_mbps': bw,
                'throughput_mbps': round(throughput_u_to_v, 2),
                'utilization': round((throughput_u_to_v / bw * 100), 2) if bw > 0 else 0,
                'packet_loss_rate': round(loss_rate, 2),
                'rx_packets_u': stats_u.get('rx_packets', 0),
                'tx_packets_u': stats_u.get('tx_packets', 0),
                'rx_dropped_u': stats_u.get('rx_dropped', 0),
                'tx_dropped_u': stats_u.get('tx_dropped', 0)
            })
        
        return link_stats

    # ============== API pública ==============

    def set_mode(self, new_mode: str):
        assert new_mode in ('hops', 'distrak')
        if new_mode != self.mode:
            self.mode = new_mode
            self.logger.info("Modo cambiado a %s", self.mode)
            self._rebuild_graph_and_push()

    def reinstall(self):
        self._rebuild_graph_and_push()


# ========================= WSGI REST =========================

class RestAPI(ControllerBase):
    def __init__(self, req, link, data, **config):
        super().__init__(req, link, data, **config)
        self.app = data[API_INSTANCE]

    @route('pr', '/set_mode', methods=['POST'])
    def set_mode(self, req, **kwargs):
        try:
            body = json.loads(req.body.decode('utf-8'))
            mode = body.get('mode')
            if mode not in ('hops', 'distrak'):
                return Response(status=400, body=b'{"error":"mode must be hops|distrak"}',
                                content_type='application/json')
            self.app.set_mode(mode)
            return Response(status=200, body=json.dumps({"mode": self.app.mode}).encode('utf-8'),
                            content_type='application/json')
        except Exception as e:
            return Response(status=500, body=json.dumps({"error": str(e)}).encode('utf-8'),
                            content_type='application/json')

    @route('pr', '/reinstall', methods=['POST'])
    def reinstall(self, req, **kwargs):
        self.app.reinstall()
        return Response(status=200, body=b'{"status":"reinstalled"}',
                        content_type='application/json')

    @route('pr', '/topology', methods=['GET'])
    def topology(self, req, **kwargs):
        nodes = list(self.app.G.nodes)
        links = []
        for (u, v, data) in self.app.G.edges(data=True):
            links.append({"u": u, "v": v, "bw": data.get("bw"), "weight": data.get("weight")})
        payload = {"mode": self.app.mode, "nodes": nodes, "links": links}
        return Response(status=200, body=json.dumps(payload).encode('utf-8'),
                        content_type='application/json')

    @route('pr', '/path', methods=['GET'])
    def path(self, req, **kwargs):
        try:
            params = req.params
            src_param = params.get('src')
            dst_param = params.get('dst')
            if not src_param or not dst_param:
                return Response(status=400, body=b'{"error":"use /path?src=<...>&dst=<...>"}',
                                content_type='application/json')

            def parse_node(x: str):
                """Acepta '7', 's7' o '10.0.0.7' y devuelve 7 (switch id)."""
                x = x.strip()
                if x.startswith('s') and x[1:].isdigit():
                    return int(x[1:])
                if x.replace('.', '').isdigit() and x.count('.') == 3:
                    parts = x.split('.')
                    if len(parts) == 4 and parts[0] == '10' and parts[1] == '0' and parts[2] == '0':
                        return int(parts[3])
                    raise ValueError("solo IPs 10.0.0.X son válidas para hosts")
                if x.isdigit():
                    return int(x)
                raise ValueError("formato de nodo no válido")

            src = parse_node(src_param)
            dst = parse_node(dst_param)

            if src not in self.app.G or dst not in self.app.G:
                return Response(status=404,
                                body=json.dumps({"error": "src o dst no están en el grafo",
                                                 "nodes": list(self.app.G.nodes)}).encode('utf-8'),
                                content_type='application/json')

            path = nx.shortest_path(self.app.G, source=src, target=dst, weight='weight')
            weight_sum = 0.0
            links = []
            for i in range(len(path)-1):
                u, v = path[i], path[i+1]
                data = self.app.G.get_edge_data(u, v, default={})
                bw = data.get('bw')
                w  = data.get('weight')
                weight_sum += (w if w is not None else 1.0)
                out_port = self.app.adj.get((u, v))
                links.append({"u": u, "v": v, "bw": bw, "weight": w, "out_port": out_port})

            payload = {
                "mode": self.app.mode,
                "src": src,
                "dst": dst,
                "path": path,
                "hops": max(0, len(path)-1),
                "weight_sum": weight_sum,
                "links": links,
                "dst_host_port": self.app.host_port.get(dst)
            }
            return Response(status=200, body=json.dumps(payload).encode('utf-8'),
                            content_type='application/json')

        except nx.NetworkXNoPath:
            return Response(status=404, body=b'{"error":"no path between src and dst"}',
                            content_type='application/json')
        except Exception as e:
            return Response(status=500, body=json.dumps({"error": str(e)}).encode('utf-8'),
                            content_type='application/json')

    # ============== NUEVO: Endpoint de estadísticas ==============
    
    @route('pr', '/stats/links', methods=['GET'])
    def stats_links(self, req, **kwargs):
        """Retorna estadísticas de todos los enlaces."""
        try:
            stats = self.app.get_link_stats()
            return Response(status=200, body=json.dumps(stats).encode('utf-8'),
                            content_type='application/json')
        except Exception as e:
            return Response(status=500, body=json.dumps({"error": str(e)}).encode('utf-8'),
                            content_type='application/json')
    
    @route('pr', '/stats/switches', methods=['GET'])
    def stats_switches(self, req, **kwargs):
        """Retorna estadísticas de todos los switches."""
        try:
            switches_stats = []
            for dpid in self.app.datapaths.keys():
                port_stats = self.app.port_stats.get(dpid, {})
                flow_count = len(self.app.flow_stats.get(dpid, []))
                
                total_rx_packets = sum(p.get('rx_packets', 0) for p in port_stats.values())
                total_tx_packets = sum(p.get('tx_packets', 0) for p in port_stats.values())
                total_rx_bytes = sum(p.get('rx_bytes', 0) for p in port_stats.values())
                total_tx_bytes = sum(p.get('tx_bytes', 0) for p in port_stats.values())
                
                switches_stats.append({
                    'dpid': dpid,
                    'flow_count': flow_count,
                    'total_rx_packets': total_rx_packets,
                    'total_tx_packets': total_tx_packets,
                    'total_rx_bytes': total_rx_bytes,
                    'total_tx_bytes': total_tx_bytes,
                    'port_count': len(port_stats)
                })
            
            return Response(status=200, body=json.dumps(switches_stats).encode('utf-8'),
                            content_type='application/json')
        except Exception as e:
            return Response(status=500, body=json.dumps({"error": str(e)}).encode('utf-8'),
                            content_type='application/json')
    
    @route('pr', '/stats/flows', methods=['GET'])
    def stats_flows(self, req, **kwargs):
        """Retorna estadísticas de flujos por switch."""
        try:
            dpid_param = req.params.get('dpid')
            
            if dpid_param:
                # Estadísticas de un switch específico
                dpid = int(dpid_param)
                flows = self.app.flow_stats.get(dpid, [])
                return Response(status=200, body=json.dumps({
                    'dpid': dpid,
                    'flows': flows
                }).encode('utf-8'), content_type='application/json')
            else:
                # Estadísticas de todos los switches
                all_flows = {}
                for dpid, flows in self.app.flow_stats.items():
                    all_flows[str(dpid)] = flows
                
                return Response(status=200, body=json.dumps(all_flows).encode('utf-8'),
                                content_type='application/json')
        except Exception as e:
            return Response(status=500, body=json.dumps({"error": str(e)}).encode('utf-8'),
                            content_type='application/json')

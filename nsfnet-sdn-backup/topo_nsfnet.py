#!/usr/bin/env python
# NSFNET (14 nodos, 21 enlaces) para Mininet + OVS
# Proactivo con RYU remoto (en otra VM).
#
# Uso:
#   sudo python topo_nsfnet.py --controller_ip 10.132.60.252 --controller_port 6653
#
# Nota: Ajusta IP/puerto al de tu VM de RYU.
import argparse
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.cli import CLI

class NSFNetTopo(Topo):
    """
    Topologia NSFNET canonica de laboratorio:
    - 14 switches (s1..s14)
    - 14 hosts (h1..h14) uno por switch
    - 21 enlaces backbone sX--sY con parametros (bw inventado, delay)
    """
    def build(self):
        # 1) Switches
        switches = {}
        for i in range(1, 15):
            switches[i] = self.addSwitch('s%d' % i)
        
        # 2) Hosts y enlaces host<->switch
        for i in switches:
            h = self.addHost('h%d' % i, ip='10.0.0.%d/24' % i)
            # Enlace host-switch (sin limites de bw para no afectar pruebas)
            self.addLink(h, switches[i], cls=TCLink)
        
        # 3) Enlaces backbone (21 en total)
        #    Formato: (a, b, bw_Mbps, delay_str)
        #    Puedes ajustar bw/delay a tu gusto para los experimentos.
        backbone = [
            (1,  2,  50, '8ms'),
            (1,  5,  30, '10ms'),
            (2,  3,  20, '12ms'),
            (2,  6,  40, '10ms'),
            (3,  4,  25, '8ms'),
            (3,  7,  35, '10ms'),
            (4,  8,  45, '7ms'),
            (5,  6,  10, '9ms'),
            (5,  9,  20, '11ms'),
            (6,  7,  50, '6ms'),
            (6, 10,  8, '10ms'),
            (7, 11,  40, '9ms'),
            (8, 12,  30, '8ms'),
            (9, 10,  40, '7ms'),
            (9, 13,  35, '12ms'),
            (10, 11, 20, '6ms'),
            (10, 14, 30, '10ms'),
            (11, 12, 45, '8ms'),
            (12, 14, 25, '9ms'),
            (13, 14, 15, '11ms'),
            (8,  11, 20, '7ms'),
        ]
        
        # 4) Crear enlaces con TCLink (simetria: mismo bw/delay en ambos sentidos)
        for a, b, bw, delay in backbone:
            self.addLink(
                switches[a], switches[b],
                cls=TCLink,
                bw=bw,          # Mbps
                delay=delay,    # p. ej., '10ms'
                loss=0,         # ajusta si quieres simular perdida
                max_queue_size=1000,
                use_htb=True
            )

def parse_args():
    p = argparse.ArgumentParser(description="NSFNET (14/21) con RemoteController (RYU)")
    p.add_argument("--controller_ip", type=str, required=True, help="IP del controlador RYU (VM remota)")
    p.add_argument("--controller_port", type=int, default=6653, help="Puerto OpenFlow del RYU (default 6653)")
    return p.parse_args()

if __name__ == '__main__':
    args = parse_args()
    topo = NSFNetTopo()
    net = Mininet(
        topo=topo,
        controller=None,   # Usaremos RemoteController
        link=TCLink,
        autoStaticArp=True
    )
    
    # Agregar controlador remoto (RYU en otra VM)
    c0 = net.addController(
        'c0',
        controller=RemoteController,
        ip=args.controller_ip,
        port=args.controller_port
    )
    
    net.start()
    
    # Tips rapidos en consola:
    print("\n=== NSFNET (14/21) iniciada ===")
    print("Controlador remoto: %s:%d" % (args.controller_ip, args.controller_port))
    print("Pruebas rapidas:")
    print("  mininet> pingall")
    print("  mininet> iperf h1 h14")
    print("  mininet> nodes; links; net")
    print("  mininet> exit\n")
    
    # CLI interactiva
    CLI(net)
    net.stop()

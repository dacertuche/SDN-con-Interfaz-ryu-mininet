#!/usr/bin/env python3
"""
Management Plane - Web Application for NSFNET SDN Controller
Provides web interface for:
- Routing mode selection (hops / distrak)
- Network topology visualization
- Performance monitoring (delay, throughput, packet loss)

Run: python3 web_app.py
Access: http://<IP>:5000
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import requests
import logging

app = Flask(__name__)
CORS(app)  # Permitir CORS para requests desde frontend

# Configuración del controlador Ryu
RYU_API_BASE = "http://192.168.0.17:8080"

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====================== RUTAS DE LA WEB ======================

@app.route('/')
def index():
    """Página principal del Management Plane."""
    return render_template('index.html')

# ====================== API ENDPOINTS ======================

@app.route('/api/topology', methods=['GET'])
def get_topology():
    """Obtiene la topología actual del controlador Ryu."""
    try:
        response = requests.get(f"{RYU_API_BASE}/topology", timeout=5)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.exceptions.RequestException as e:
        logger.error(f"Error obteniendo topología: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/mode', methods=['GET'])
def get_mode():
    """Obtiene el modo de enrutamiento actual."""
    try:
        response = requests.get(f"{RYU_API_BASE}/topology", timeout=5)
        response.raise_for_status()
        data = response.json()
        return jsonify({"mode": data.get("mode", "unknown")})
    except requests.exceptions.RequestException as e:
        logger.error(f"Error obteniendo modo: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/mode', methods=['POST'])
def set_mode():
    """Cambia el modo de enrutamiento."""
    try:
        data = request.get_json()
        mode = data.get('mode')
        
        if mode not in ['hops', 'distrak']:
            return jsonify({"error": "Mode must be 'hops' or 'distrak'"}), 400
        
        response = requests.post(
            f"{RYU_API_BASE}/set_mode",
            json={"mode": mode},
            headers={'Content-Type': 'application/json'},
            timeout=5
        )
        response.raise_for_status()
        
        logger.info(f"Modo cambiado a: {mode}")
        return jsonify(response.json())
    except requests.exceptions.RequestException as e:
        logger.error(f"Error cambiando modo: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/path', methods=['GET'])
def get_path():
    """Obtiene la ruta entre dos nodos."""
    try:
        src = request.args.get('src')
        dst = request.args.get('dst')
        
        if not src or not dst:
            return jsonify({"error": "Parameters 'src' and 'dst' required"}), 400
        
        response = requests.get(
            f"{RYU_API_BASE}/path",
            params={'src': src, 'dst': dst},
            timeout=5
        )
        response.raise_for_status()
        return jsonify(response.json())
    except requests.exceptions.RequestException as e:
        logger.error(f"Error obteniendo ruta: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/stats/links', methods=['GET'])
def get_link_stats():
    """Obtiene estadísticas de todos los enlaces."""
    try:
        response = requests.get(f"{RYU_API_BASE}/stats/links", timeout=5)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.exceptions.RequestException as e:
        logger.error(f"Error obteniendo estadísticas de enlaces: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/stats/switches', methods=['GET'])
def get_switch_stats():
    """Obtiene estadísticas de todos los switches."""
    try:
        response = requests.get(f"{RYU_API_BASE}/stats/switches", timeout=5)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.exceptions.RequestException as e:
        logger.error(f"Error obteniendo estadísticas de switches: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/stats/flows', methods=['GET'])
def get_flow_stats():
    """Obtiene estadísticas de flujos."""
    try:
        dpid = request.args.get('dpid')
        params = {'dpid': dpid} if dpid else {}
        
        response = requests.get(
            f"{RYU_API_BASE}/stats/flows",
            params=params,
            timeout=5
        )
        response.raise_for_status()
        return jsonify(response.json())
    except requests.exceptions.RequestException as e:
        logger.error(f"Error obteniendo estadísticas de flujos: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/stats/summary', methods=['GET'])
def get_stats_summary():
    """Obtiene un resumen de estadísticas de la red."""
    try:
        # Obtener estadísticas de enlaces
        links_resp = requests.get(f"{RYU_API_BASE}/stats/links", timeout=5)
        links_resp.raise_for_status()
        links_data = links_resp.json()
        
        # Obtener estadísticas de switches
        switches_resp = requests.get(f"{RYU_API_BASE}/stats/switches", timeout=5)
        switches_resp.raise_for_status()
        switches_data = switches_resp.json()
        
        # Calcular resumen
        total_throughput = sum(link.get('throughput_mbps', 0) for link in links_data)
        avg_utilization = (
            sum(link.get('utilization', 0) for link in links_data) / len(links_data)
            if links_data else 0
        )
        total_packet_loss = sum(link.get('packet_loss_rate', 0) for link in links_data)
        total_packets = sum(sw.get('total_tx_packets', 0) for sw in switches_data)
        
        summary = {
            'total_switches': len(switches_data),
            'total_links': len(links_data),
            'total_throughput_mbps': round(total_throughput, 2),
            'avg_link_utilization': round(avg_utilization, 2),
            'total_packet_loss_rate': round(total_packet_loss, 2),
            'total_packets_forwarded': total_packets,
            'links': links_data,
            'switches': switches_data
        }
        
        return jsonify(summary)
    except requests.exceptions.RequestException as e:
        logger.error(f"Error obteniendo resumen de estadísticas: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/reinstall', methods=['POST'])
def reinstall_flows():
    """Fuerza la reinstalación de flujos en el controlador."""
    try:
        response = requests.post(f"{RYU_API_BASE}/reinstall", timeout=10)
        response.raise_for_status()
        logger.info("Flujos reinstalados correctamente")
        return jsonify(response.json())
    except requests.exceptions.RequestException as e:
        logger.error(f"Error reinstalando flujos: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Verifica el estado de la aplicación y del controlador."""
    try:
        # Verificar conectividad con Ryu
        response = requests.get(f"{RYU_API_BASE}/topology", timeout=2)
        ryu_status = "ok" if response.status_code == 200 else "error"
    except:
        ryu_status = "disconnected"
    
    return jsonify({
        "flask_app": "ok",
        "ryu_controller": ryu_status,
        "ryu_api_base": RYU_API_BASE
    })

# ====================== MANEJO DE ERRORES ======================

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

# ====================== MAIN ======================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description="NSFNET Management Plane Web App")
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind (default: 5000)')
    parser.add_argument('--ryu-api', default='http://localhost:8080', 
                        help='Ryu API base URL (default: http://localhost:8080)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    
    # Configurar URL del controlador Ryu
    RYU_API_BASE = args.ryu_api
    
    logger.info(f"Starting NSFNET Management Plane")
    logger.info(f"Ryu Controller API: {RYU_API_BASE}")
    logger.info(f"Web Interface: http://{args.host}:{args.port}")
    
    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug,
        threaded=True
    )

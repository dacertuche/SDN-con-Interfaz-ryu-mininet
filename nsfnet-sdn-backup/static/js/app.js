// NSFNET Management Plane - Frontend Logic

// Configuration
const API_BASE = '/api';
const REFRESH_INTERVAL = 5000; // 5 seconds

// Global state
let network = null;
let utilizationChart = null;
let throughputChart = null;
let currentMode = 'unknown';

// Initialize application
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Initializing NSFNET Management Plane...');
    initializeApp();
    setupEventListeners();
    startAutoRefresh();
});

// ======================  INITIALIZATION ======================

function initializeApp() {
    checkControllerStatus();
    loadTopology();
    loadCurrentMode();
    loadStats();
}

function setupEventListeners() {
    document.getElementById('apply-mode').addEventListener('click', applyRoutingMode);
    document.getElementById('calculate-path').addEventListener('click', calculatePath);
    document.getElementById('refresh-stats').addEventListener('click', () => {
        loadStats();
        showNotification('Stats refreshed', 'success');
    });
    document.getElementById('reinstall-flows').addEventListener('click', reinstallFlows);
}

function startAutoRefresh() {
    setInterval(() => {
        loadStats();
        updateLastUpdateTime();
    }, REFRESH_INTERVAL);
}

// ======================  API CALLS ======================

async function apiCall(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, options);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error(`API call failed: ${endpoint}`, error);
        throw error;
    }
}

async function checkControllerStatus() {
    try {
        await apiCall('/topology');
        updateControllerStatus(true);
    } catch (error) {
        updateControllerStatus(false);
    }
}

function updateControllerStatus(connected) {
    const statusBadge = document.getElementById('controller-status');
    const statusText = document.getElementById('status-text');
    
    if (connected) {
        statusBadge.classList.add('connected');
        statusText.textContent = 'Connected';
    } else {
        statusBadge.classList.remove('connected');
        statusText.textContent = 'Disconnected';
    }
}

async function loadCurrentMode() {
    try {
        const data = await apiCall('/mode');
        currentMode = data.mode;
        document.getElementById('current-mode').textContent = currentMode.toUpperCase();
        document.getElementById('routing-mode').value = currentMode;
    } catch (error) {
        console.error('Failed to load current mode', error);
    }
}

async function applyRoutingMode() {
    const mode = document.getElementById('routing-mode').value;
    
    try {
        const data = await apiCall('/mode', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode})
        });
        
        currentMode = data.mode;
        document.getElementById('current-mode').textContent = currentMode.toUpperCase();
        showNotification(`Routing mode changed to ${currentMode.toUpperCase()}`, 'success');
        
        setTimeout(() => {
            loadTopology();
            loadStats();
        }, 1000);
    } catch (error) {
        showNotification('Failed to change routing mode', 'error');
    }
}

async function calculatePath() {
    const src = document.getElementById('path-src').value.trim();
    const dst = document.getElementById('path-dst').value.trim();
    
    if (!src || !dst) {
        showNotification('Please enter source and destination', 'error');
        return;
    }
    
    try {
        const data = await apiCall(`/path?src=${encodeURIComponent(src)}&dst=${encodeURIComponent(dst)}`);
        displayPathResult(data);
    } catch (error) {
        showNotification('Failed to calculate path', 'error');
    }
}

function displayPathResult(data) {
    const resultDiv = document.getElementById('path-result');
    const pathStr = data.path.join(' → ');
    
    resultDiv.innerHTML = `
        <h4>Path Found</h4>
        <p><strong>Mode:</strong> ${data.mode.toUpperCase()}</p>
        <p><strong>Path:</strong> ${pathStr}</p>
        <p><strong>Hops:</strong> ${data.hops}</p>
        <p><strong>Weight Sum:</strong> ${data.weight_sum.toFixed(3)}</p>
    `;
    resultDiv.classList.add('show');
    
    // NUEVO: Resaltar el camino en la topología
    highlightPathInTopology(data.path);
}

// NUEVA FUNCIÓN: Resaltar el camino en el grafo
function highlightPathInTopology(path) {
    if (!network) return;
    
    const nodes = network.body.data.nodes;
    const edges = network.body.data.edges;
    
    // 1. Resetear todos los nodos y enlaces a su color normal
    nodes.forEach(node => {
        nodes.update({
            id: node.id,
            color: {
                background: '#2563eb',
                border: '#1d4ed8'
            },
            borderWidth: 1
        });
    });
    
    // 2. Resetear todos los enlaces
    edges.forEach(edge => {
        edges.update({
            id: edge.id,
            width: 2,
            color: {color: '#10b981'}
        });
    });
    
    // 3. Resaltar nodos en el path
    path.forEach(nodeId => {
        nodes.update({
            id: nodeId,
            color: {
                background: '#f59e0b',  // Naranja
                border: '#d97706'
            },
            borderWidth: 4
        });
    });
    
    // 4. Resaltar enlaces en el path
    for (let i = 0; i < path.length - 1; i++) {
        const fromNode = path[i];
        const toNode = path[i + 1];
        
        // Buscar el enlace entre estos dos nodos
        const edgeIds = edges.getIds({
            filter: item => 
                (item.from === fromNode && item.to === toNode) || 
                (item.from === toNode && item.to === fromNode)
        });
        
        if (edgeIds.length > 0) {
            edges.update({
                id: edgeIds[0],
                width: 5,
                color: {
                    color: '#f59e0b',      // Naranja
                    highlight: '#d97706'
                },
                arrows: {
                    to: {
                        enabled: true,
                        scaleFactor: 0.5
                    }
                }
            });
        }
    }
    
    // 5. Enfocar en el camino (opcional)
    network.fit({
        nodes: path,
        animation: {
            duration: 1000,
            easingFunction: 'easeInOutQuad'
        }
    });
}

async function reinstallFlows() {
    if (!confirm('Are you sure you want to reinstall all flows?')) {
        return;
    }
    
    try {
        await apiCall('/reinstall', {method: 'POST'});
        showNotification('Flows reinstalled successfully', 'success');
        setTimeout(() => loadStats(), 2000);
    } catch (error) {
        showNotification('Failed to reinstall flows', 'error');
    }
}

// ======================  TOPOLOGY VISUALIZATION ======================

async function loadTopology() {
    try {
        const data = await apiCall('/topology');
        renderTopology(data);
    } catch (error) {
        console.error('Failed to load topology', error);
    }
}

function renderTopology(data) {
    const container = document.getElementById('topology-container');
    
    const nodes = data.nodes.map(id => ({
        id: id,
        label: `s${id}`,
        shape: 'box',
        color: {
            background: '#2563eb',
            border: '#1d4ed8'
        },
        font: {color: '#ffffff', size: 14}
    }));
    
    const edges = data.links.map((link, index) => ({
        id: index,  // Agregar ID único
        from: link.u,
        to: link.v,
        label: `${link.bw}M`,
        color: {color: '#10b981'},
        width: 2
    }));
    
    const networkData = {
        nodes: new vis.DataSet(nodes), 
        edges: new vis.DataSet(edges)
    };
    
    const options = {
        physics: {enabled: true, solver: 'forceAtlas2Based'},
        layout: {improvedLayout: true}
    };
    
    if (network) {
        network.destroy();
    }
    
    network = new vis.Network(container, networkData, options);
    updateTopologyWithStats();
}

async function updateTopologyWithStats() {
    if (!network) return;
    
    try {
        const stats = await apiCall('/stats/links');
        const edges = network.body.data.edges;
        
        stats.forEach(link => {
            const edgeIds = edges.getIds({
                filter: item => (item.from === link.src && item.to === link.dst) || 
                               (item.from === link.dst && item.to === link.src)
            });
            
            if (edgeIds.length > 0) {
                const color = link.utilization < 30 ? '#10b981' : 
                             link.utilization < 70 ? '#f59e0b' : '#ef4444';
                edges.update({id: edgeIds[0], color: {color: color}});
            }
        });
    } catch (error) {
        console.error('Failed to update topology', error);
    }
}

// ======================  STATISTICS ======================

async function loadStats() {
    try {
        const summary = await apiCall('/stats/summary');
        updateMetricsCards(summary);
        updateLinkStatsTable(summary.links);
        updateCharts(summary.links);
        updateTopologyWithStats();
    } catch (error) {
        console.error('Failed to load stats', error);
    }
}

function updateMetricsCards(summary) {
    document.getElementById('total-throughput').textContent = summary.total_throughput_mbps.toFixed(2);
    document.getElementById('avg-utilization').textContent = summary.avg_link_utilization.toFixed(1);
    document.getElementById('packet-loss').textContent = summary.total_packet_loss_rate.toFixed(2);
    document.getElementById('total-packets').textContent = summary.total_packets_forwarded.toLocaleString();
}

function updateLinkStatsTable(links) {
    const tbody = document.getElementById('link-stats-body');
    
    if (links.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="no-data">No data available</td></tr>';
        return;
    }
    
    tbody.innerHTML = links.map(link => {
        const utilClass = link.utilization < 30 ? 'util-low' : 
                         link.utilization < 70 ? 'util-medium' : 'util-high';
        
        return `
            <tr>
                <td>s${link.src} ↔ s${link.dst}</td>
                <td>${link.bw_mbps}</td>
                <td>${link.throughput_mbps.toFixed(2)}</td>
                <td class="${utilClass}">${link.utilization.toFixed(1)}%</td>
                <td>${link.packet_loss_rate.toFixed(2)}%</td>
                <td>${link.tx_packets_u.toLocaleString()}</td>
                <td>${link.rx_packets_u.toLocaleString()}</td>
            </tr>
        `;
    }).join('');
}

function updateCharts(links) {
    if (links.length === 0) return;
    
    const labels = links.map(l => `s${l.src}-s${l.dst}`);
    const utilization = links.map(l => l.utilization);
    const throughput = links.map(l => l.throughput_mbps);
    
    const utilizationCtx = document.getElementById('utilization-chart').getContext('2d');
    
    if (utilizationChart) {
        utilizationChart.destroy();
    }
    
    utilizationChart = new Chart(utilizationCtx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Utilization (%)',
                data: utilization,
                backgroundColor: utilization.map(u => u < 30 ? '#10b981' : u < 70 ? '#f59e0b' : '#ef4444')
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {y: {beginAtZero: true, max: 100}}
        }
    });
    
    const throughputCtx = document.getElementById('throughput-chart').getContext('2d');
    
    if (throughputChart) {
        throughputChart.destroy();
    }
    
    throughputChart = new Chart(throughputCtx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Throughput (Mbps)',
                data: throughput,
                borderColor: '#7c3aed',
                backgroundColor: 'rgba(124, 58, 237, 0.1)',
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {y: {beginAtZero: true}}
        }
    });
}

// ======================  UTILITIES ======================

function showNotification(message, type) {
    const color = type === 'success' ? '#10b981' : '#ef4444';
    console.log('%c' + message, 'color: ' + color + '; font-weight: bold;');
}

function updateLastUpdateTime() {
    const now = new Date();
    document.getElementById('last-update').textContent = now.toLocaleTimeString();
}

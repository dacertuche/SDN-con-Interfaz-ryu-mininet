README – Sistema SDN NSFNET con Ryu, Mininet y Flask

Descripción general:
Este proyecto implementa un entorno de red definida por software (SDN) utilizando el controlador Ryu, la plataforma Mininet y una aplicación web desarrollada con Flask para la monitorización del rendimiento y la selección del tipo de enrutamiento. La topología de red utilizada corresponde a la NSFNET, construida mediante Mininet, y se conecta con el controlador Ryu por medio del protocolo OpenFlow.

El sistema se divide en dos máquinas virtuales que trabajan de manera coordinada:

* VM1: encargada del plano de reenvío (Forwarding Plane) mediante Mininet y Open vSwitch.
* VM2: encargada del plano de control (Control Plane) y del plano de gestión (Management Plane), ejecutando el controlador Ryu y el servidor Flask que proporciona la interfaz web.

---

REQUISITOS DEL SISTEMA

Sistema Operativo: Windows / macOS / Linux
Hipervisor: VirtualBox, VMware o KVM
Navegador Web: para acceder a la interfaz de monitorización

---

ENTORNO DE IMPLEMENTACIÓN

VM1: Mininet

* Sistema operativo: Ubuntu 16.04 o 18.04
* Versión de Python: 2.7
* Componentes instalados:

  * Script topo_nsfnet.py
  * Mininet
  * Open vSwitch

VM2: Ryu + Flask

* Sistema operativo: Ubuntu 20.04 o 22.04
* Versión de Python: 3.9 o superior
* Componentes instalados:

  * Script ryu_app.py
  * Script web_app.py
  * Carpetas templates/ y static/ para la interfaz web
* Comunicación entre VM1 y VM2 mediante el protocolo OpenFlow en el puerto 6653

---

DESCRIPCIÓN FUNCIONAL

Plano de Forwarding:
Se trabaja con Open vSwitch dentro de la topología creada en Mininet (NSFNET). Esta topología define los hosts y switches interconectados y se ejecuta mediante el script topo_nsfnet.py.

Plano de Control:
El controlador Ryu recibe la información de la topología mediante OpenFlow y gestiona el enrutamiento proactivo. La aplicación ryu_app.py implementa el cálculo de rutas utilizando la librería NetworkX, con dos modos de funcionamiento:

1. Modo Distrak: el peso de cada enlace se define como 1/Bw (inverso del ancho de banda).
2. Modo por saltos: calcula la ruta con el menor número de saltos.

Plano de Gestión (Management Plane):
El servidor Flask (web_app.py) proporciona una interfaz web que permite al usuario seleccionar el tipo de enrutamiento (Distrak o por saltos) y visualizar las métricas de la red, incluyendo:

* Retardo (Delay)
* Rendimiento (Throughput)
* Pérdida de paquetes (Packet loss)

---

PREPARACIÓN DEL ENTORNO

1. Acceder por SSH a cada máquina virtual (una para Mininet y otra para Ryu).
2. En la máquina del controlador Ryu, activar el entorno virtual de Python:
   source ~/ryu-venv/bin/activate
3. Verificar que Flask esté instalado correctamente:
   python -c "import flask; print('Flask OK:', flask.**version**)"
4. Instalar las dependencias necesarias:
   pip install flask eventlet networkx

---

EJECUCIÓN DEL CONTROLADOR RYU

1. Acceder al directorio del controlador:
   cd ~/nsfnet-sdn/controller
2. Ejecutar el controlador Ryu con observación de enlaces:
   ryu-manager --observe-links ryu_app.py

El parámetro --observe-links permite descubrir los enlaces mediante LLDP y construir el grafo de red automáticamente.

---

EJECUCIÓN DE LA APLICACIÓN WEB

1. Acceder al directorio web:
   cd ~/nsfnet-sdn/web
2. Ejecutar el servidor Flask:
   python web_app.py --host 0.0.0.0 --port 5000
3. Acceder a la interfaz desde un navegador con la dirección:
   http://IP_DEL_CONTROLADOR:5000

Desde esta interfaz se pueden visualizar las métricas de la red y seleccionar el tipo de enrutamiento a utilizar.

---

EJECUCIÓN DE LA TOPOLOGÍA NSFNET

1. Acceder a la máquina virtual que ejecuta Mininet.
2. Entrar al directorio donde se encuentra el archivo topo_nsfnet.py:
   cd ~/nsfnet-sdn/mininet
3. Ejecutar el script indicando la dirección IP y el puerto del controlador:
   sudo python3 topo_nsfnet.py --controller_ip 10.132.60.252 --controller_port 6653

Este comando levanta la topología NSFNET, crea los switches, hosts y enlaces, y los asocia al controlador Ryu.

---

PRUEBAS DE TRÁFICO Y MÉTRICAS

Para generar tráfico entre hosts y obtener métricas:

1. Desde la consola de Mininet, iniciar un servidor iperf en un host:
   h1 iperf -s &
2. En otro host, generar tráfico UDP con tasa de 5 Mbps durante 60 segundos:
   h2 iperf -c 10.0.0.14 -u -b 5M -t 60 &
3. Para verificar conectividad y retardo:
   h1 ping -c 10 h2

Los resultados de throughput, delay y pérdida de paquetes podrán visualizarse en la aplicación web.

---

ARQUITECTURA GENERAL

El sistema completo se compone de dos máquinas virtuales:

* VM1 (Mininet): genera la topología, crea los nodos y define los enlaces con ancho de banda asignado manualmente.
* VM2 (Ryu + Flask): controla la red mediante OpenFlow y proporciona la interfaz web para monitorización.

La comunicación entre ambas máquinas se realiza sobre el puerto 6653, utilizando OpenFlow. El controlador Ryu gestiona los flujos de forma proactiva y la aplicación web permite observar el comportamiento y rendimiento de la red.

---

ENTREGABLES DEL PROYECTO

* Sistema funcional completamente operativo.
* Video demostrativo del funcionamiento.
* Presentación de sustentación (máximo 10 minutos).
* Diagramas de apoyo (despliegue, secuencia y estados).

---

NOTAS IMPORTANTES

* Asegurarse de que las direcciones IP del controlador y la topología sean alcanzables entre sí.
* En caso de errores de conexión, verificar el puerto de OpenFlow y la ejecución de ryu-manager.
* La topología y el controlador deben mantenerse activos mientras se ejecuta la aplicación web.
* Los anchos de banda definidos en la topología son inventados para simular escenarios de red con distintos pesos.
* En el modo Distrak, las rutas se recalculan según el peso inverso del ancho de banda (1/Bw), priorizando enlaces más rápidos.

---

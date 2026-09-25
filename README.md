# BioScope: High-Altitude Biological Incubator & Data Farm

## Overview
BioScope is a low-cost, automated bacteria incubator designed to study bacterial growth and antibiotic inhibition zones.  

## Core Architecture

### Hardware & Actuation
*   **Microcontroller:** ESP32 handling control loops.
*   **Thermal Actuators:** 200W PTC Ceramic Heater (driven by BTS7960 MOSFET H-Bridge) and a Peltier cooler (driven by AOD4184A MOSFET module).
*   **Sensors:** SHT31
*   **Vision:** Logitech C920 HD Pro.

### Software & Control Theory
*   **Supervisory Limit Scheduling:** Pure PI control logic augmented with a dynamic state-machine. The system physically restricts the 200W heater to 20% PWM during the initial approach to eliminate inertial overshoot, then dynamically shifts the ceiling to 30% at steady-state to combat the non-linear electrical resistance of the warm PTC core.
*   **Active Anti-Windup:** Independent integral clamping prevents asymmetrical thermal runaway during active cooling cycles.
*   **Python Data Pipeline:** A persistent asynchronous script that decouples the fast 2-second hardware control loop from the storage architecture. It records thermal telemetry every 1 minute and triggers high-resolution image captures every 5 minutes, mitigating storage bloat over 24-hour experiments.

## Data Structure
The system automatically generates a relational CSV database at the conclusion of each experiment, pairing environmental conditions directly with the corresponding optical frame for that specific timestamp:

| Timestamp | Setpoint (°C) | Temp (°C) | Hum (%) | Image_File |
| :--- | :--- | :--- | :--- | :--- |
| 14:00:00 | 37.0 | 37.02 | 45.1 | img_1400.jpg |
| 14:01:00 | 37.0 | 37.01 | 45.0 | None |
| 14:05:00 | 37.0 | 36.98 | 45.1 | img_1405.jpg |

## Repository Structure
*   `/firmware`: Contains the ESP32 C++ source code, including `main.cpp` and the custom `SplitRangePID` class.
*   `/software`: Contains the Python GUI, serial communication parser, and data logging scripts.
*   `/cad`: 3D printable files (STL/STEP) for the sensor mounts and the 160 mm optical rig.
*   `/data`: Sample datasets and timelapse MP4s generated from 24-hour baseline runs.

## Setup & Usage
1.  **Hardware:** Ensure the ESP32 is connected via USB and the PTC heater driver is supplied with adequate external power. 
2.  **Firmware:** Flash the `/firmware` directory to the ESP32 using PlatformIO or Arduino IDE.
3.  **Software:** Install Python dependencies (`pip install pyserial matplotlib`).
4.  **Execution:** Run `realtime_plot.py`. The system enters a safe idle state until the `START` command is issued via the GUI, initializing the 24-hour automated cycle.

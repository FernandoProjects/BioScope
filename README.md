# BioScope: High-Altitude Biological Incubator & Data Farm

## Overview
BioScope is a low-cost, automated bacteria incubator designed to study bacterial growth and antibiotic inhibition zones.  

## Core Architecture

### Hardware & Actuation
*   **Microcontroller:** ESP32 handling control loops.
*   **Thermal Actuators:** 200W PTC Ceramic Heater (driven by BTS7960 MOSFET H-Bridge) and a Peltier cooler (driven by AOD4184A MOSFET module).
*   **Sensors:** SHT31
*   **Vision:** Logitech C920 HD Pro.
*   **Image processing and GUI:** Raspberry Pi 4

### Control system
*   **Supervisory Limit Scheduling:** PI control logic augmented with a dynamic state-machine. The system physically restricts the 200W heater to 20% PWM during the initial approach to eliminate inertial overshoot, then dynamically shifts the ceiling to 30% at steady-state to combat the non-linear electrical resistance of the warm PTC core.
*   **Active Anti-Windup:** Independent integral clamping prevents asymmetrical thermal runaway during active cooling cycles.

## Data Structure
The system automatically generates 2 CSV files at the conclusion of each experiment, one for environmental data and the other one for inhibiton zone areas.

## Repository Structure
*   `/src`: Contains the ESP32 C++ source code, including `main.cpp` and the custom `SplitRangePID` class.
*   `/interface/cultivo_app`: Contains the GUI and computer vision model.
*   `/software`: Contains the Python GUI, serial communication parser, and data logging scripts.
*   `/cad`: 2D designs for the laser-cut MDF walls and 3D printable files (STL/STEP) for the sensor mounts and optical rig.


# BioScope: High-Altitude Biological Incubator & Data Farm

## Overview
BioScope is a low-cost, automated bacteria incubator designed to study bacterial growth and antibiotic inhibition zones.  
<img width="3438*0.5" height="1851*0.5" alt="IMG_6736" src="https://github.com/user-attachments/assets/76f27a21-5478-4814-82f3-1df4af8719c3" />
<img width="2918" height="2647" alt="IMG_6742" src="https://github.com/user-attachments/assets/497fc104-c2fb-4fb1-9118-30a0efd73dac" />

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
*   `/interface/cultivo_app`: Contains the GUI `main.py` and computer vision processing `vision_halos.py`.
*   `/software`: Contains the Python GUI, serial communication parser, and data logging scripts.

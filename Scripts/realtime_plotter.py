import serial
import time
import matplotlib.pyplot as plt
import matplotlib.animation as animation

# Configuration
COM_PORT = "COM3"
BAUD_RATE = 115200
WINDOW_SIZE = 300

# Data arrays for plotting
time_data = []
temp_data = []
hum_data = []
setpoint_data = []

# Initialize Serial
try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
    print(f"Connected to {COM_PORT} at {BAUD_RATE} baud.")
    time.sleep(2)
except Exception as e:
    print(f"Could not open serial port {COM_PORT}.\n{e}")
    exit()

input("\nPress ENTER to start the control loop and launch the plot...")
print("Sending START command...")
ser.write(b"START\n")

# Set up live temperature Matplotlib figure
fig, ax = plt.subplots()
ax.set_title("Live Incubator Temperature")
ax.set_xlabel("Time (Samples)")
ax.set_ylabel("Temperature (°C)")

(line_temp,) = ax.plot([], [], label="SHT31 Temp", color="blue", linewidth=2)
(line_setpoint,) = ax.plot(
    [], [], label="Setpoint", color="red", linestyle="--", linewidth=2
)
ax.legend()

sample_count = 0


def update_plot(frame):
    global sample_count

    if ser.in_waiting > 0:
        try:
            line = ser.readline().decode("utf-8").strip()
            parts = line.split(",")

            if len(parts) == 5:
                setpoint = float(parts[0])
                current_temp = float(parts[1])
                current_hum = float(parts[2])
                heater_effort = float(parts[3])

                # Append to data arrays
                time_data.append(sample_count)
                setpoint_data.append(setpoint)
                temp_data.append(current_temp)
                hum_data.append(current_hum)

                sample_count += 1

                # Update the live temperature lines
                line_temp.set_data(time_data, temp_data)
                line_setpoint.set_data(time_data, setpoint_data)

                # Scroll the X axis
                ax.set_xlim(max(0, sample_count - WINDOW_SIZE), sample_count + 5)

                min_y = min(min(temp_data), setpoint) - 2
                max_y = max(max(temp_data), setpoint) + 2
                ax.set_ylim(min_y, max_y)

                # Terminal output
                print(
                    f"Sample {sample_count:<4} | Setpoint: {setpoint:.2f}°C | Temp: {current_temp:.2f}°C | Hum: {current_hum:.1f}% | Heater: {heater_effort:.1f}%"
                )

        except Exception as e:
            pass

    return line_temp, line_setpoint


# Run live animation
ani = animation.FuncAnimation(fig, update_plot, interval=100, cache_frame_data=False)

plt.show()

# Shutdown and final report generation
print("\nLive plot closed. Stopping hardware...")
ser.write(b"STOP\n")
ser.close()

print("Generating final session report...")

fig_final, (ax_temp, ax_hum) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
fig_final.suptitle(
    f"Incubator Final Session Report ({sample_count} samples)", fontsize=14
)

# Subplot 1: Full Temperature History
ax_temp.plot(time_data, temp_data, label="Temperature", color="blue", linewidth=2)
ax_temp.plot(
    time_data, setpoint_data, label="Setpoint", color="red", linestyle="--", linewidth=2
)
ax_temp.set_ylabel("Temperature (°C)")
ax_temp.grid(True)
ax_temp.legend()

# Subplot 2: Full Humidity History
ax_hum.plot(time_data, hum_data, label="Humidity", color="green", linewidth=2)
ax_hum.set_ylabel("Humidity (%)")
ax_hum.set_xlabel("Time (Samples)")
ax_hum.grid(True)
ax_hum.legend()

plt.tight_layout()
plt.show()

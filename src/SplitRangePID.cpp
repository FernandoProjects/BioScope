#include "SplitRangePID.h"

SplitRangePID::SplitRangePID(double deadband_val) {
    deadband = deadband_val;
    integral = 0.0;
    prev_pv = 0.0;
    first_run = true;
    heat_max = 100.0;
    cool_max = 100.0;
}

void SplitRangePID::setHeaterGains(double kp, double ki, double kd) {
    Kp_heat = kp; Ki_heat = ki; Kd_heat = kd;
}

void SplitRangePID::setCoolerGains(double kp, double ki, double kd) {
    Kp_cool = kp; Ki_cool = ki; Kd_cool = kd;
}

void SplitRangePID::setOutputLimits(double h_max, double c_max) {
    heat_max = h_max; 
    cool_max = c_max;
}

void SplitRangePID::compute(double setpoint, double pv, double dt, double &heater_out, double &cooler_out) {
    heater_out = 0.0;
    cooler_out = 0.0;

    double error = setpoint - pv;

    if (first_run) {
        prev_pv = pv;
        first_run = false;
    }

    double Kp, Ki, Kd;
    if (error > 0) {
        Kp = Kp_heat; Ki = Ki_heat; Kd = Kd_heat;
    } else {
        Kp = Kp_cool; Ki = Ki_cool; Kd = Kd_cool;
    }

    double P_out = Kp * error;

    integral += (Ki * error * dt);
    
    // Anti-windup
    if (integral > heat_max) integral = heat_max;
    if (integral < -cool_max) integral = -cool_max;

    double dpv = (pv - prev_pv) / dt;
    double D_out = -Kd * dpv;
    prev_pv = pv;

    if (error > -deadband && error < deadband) {
        return; 
    }

    double total_out = P_out + integral + D_out;

    if (total_out > 0) {
        heater_out = total_out;
        if (heater_out > heat_max) heater_out = heat_max;
    } else if (total_out < 0) {
        cooler_out = -total_out; 
        if (cooler_out > cool_max) cooler_out = cool_max;
    }
}

void SplitRangePID::reset() {
    integral = 0.0;
    first_run = true;
}
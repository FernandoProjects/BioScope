#ifndef SPLIT_RANGE_PID_H
#define SPLIT_RANGE_PID_H

class SplitRangePID {
private:
    double Kp_heat, Ki_heat, Kd_heat;
    double Kp_cool, Ki_cool, Kd_cool;
    double integral;
    double prev_pv;
    bool first_run;
    double deadband;    
    double heat_max, cool_max; 

public:
    SplitRangePID(double deadband_val);
    void setHeaterGains(double kp, double ki, double kd);
    void setCoolerGains(double kp, double ki, double kd);
    
    void setOutputLimits(double h_max, double c_max); 
    
    void compute(double setpoint, double pv, double dt, double &heater_out, double &cooler_out);
    void reset();
};

#endif
import numpy as np

class RK4Solver:
    def __init__(self, f, y0, t0, t_end, dt):
        self.f = f  # Derivative function
        self.y0 = y0  # Initial condition
        self.t0 = t0  # Start time
        self.t_end = t_end  # End time
        self.dt = dt  # Time step

    def solve(self):
        t_values = np.arange(self.t0, self.t_end, self.dt)
        y_values = np.zeros((len(t_values), len(self.y0)))
        y_values[0] = self.y0

        for i in range(1, len(t_values)):
            t = t_values[i-1]
            y = y_values[i-1]
            k1 = self.dt * self.f(t, y)
            k2 = self.dt * self.f(t + 0.5 * self.dt, y + 0.5 * k1)
            k3 = self.dt * self.f(t + 0.5 * self.dt, y + 0.5 * k2)
            k4 = self.dt * self.f(t + self.dt, y + k3)
            y_values[i] = y + (k1 + 2*k2 + 2*k3 + k4) / 6

        return t_values, y_values

# Example of a derivative function
def derivative_function(t, y):
    dydt = -y + np.sin(t)  # Example of a simple harmonic oscillator
    return dydt

if __name__ == '__main__':
    # Initialize parameters
    y0 = [0]  # Initial condition
    t0 = 0  # Start time
    t_end = 10  # End time
    dt = 0.1  # Time step

    # Create an RK4 solver instance
    rk4_solver = RK4Solver(derivative_function, y0, t0, t_end, dt)
    t_values, y_values = rk4_solver.solve()

    # Save the training data (t_values, y_values)
    np.savez('training_data.npz', t=t_values, y=y_values)
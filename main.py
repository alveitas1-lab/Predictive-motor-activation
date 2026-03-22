# Flight Control Logic

class FlightController:
    def __init__(self):
        #positional coordinates
        self.x = 0 # east/west position
        self.y = 0 # north/south position
        self.z = 0 # altitude
        #velocity components
        self.vx = 0 # speed in x
        self.vy = 0 # speed in y
        self.vz = 0 # speed in z

    def ascend(self, feet):
        self.z += feet
        print(f'Ascended to {self.z} feet.')

    def descend(self, feet):
        if self.z - feet < 0:
            print('Cannot descend below z = 0 feet!')
        else:
            self.z -= feet
            print(f'Descended to {self.z} feet.')

    def move_x(self, feet):
        self.x += feet
        print(f'Moved to x = {self.x} feet.')

    def move_y(self, feet):
        self.y += feet
        print(f'Moved to y = {self.y} feet.')

    def set_velocity(self, vzx, vy, vz):
        self.vx = vx
        self.vy = vy
        self.vz = vz
        print(f'Velocity is ({self.vx}, {self.vy}, {self.vz}) ft/s')

    def status(self):
        print(f'Position: ({self.x}, {self.y}, {self.z}) feet')
        print(f'Velocity: ({self.vx}, {self.vy}, {self.vz}) ft/s')
    

# Example Usage
if __name__ == '__main__':
    fc = FlightController()
    fc.ascend()
    fc.move_x()
    fc.move_y()
    fc.set_velocity()
    fc.descend()
    fc.status()

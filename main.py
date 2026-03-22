# Flight Control Logic

class FlightController:
    def __init__(self):
        self.altitude = 0
        self.speed = 0
        self.direction = 'N'

    def ascend(self, feet):
        self.altitude += feet
        print(f'Ascended to {self.altitude} feet.')

    def descend(self, feet):
        if self.altitude - feet < 0:
            print('Cannot descend below 0 feet!')
        else:
            self.altitude -= feet
            print(f'Descended to {self.altitude} feet.')

    def set_speed(self, speed):
        self.speed = speed
        print(f'Speed set to {self.speed} knots.')

    def change_direction(self, direction):
        self.direction = direction
        print(f'Direction changed to {self.direction}.')

# Example Usage
if __name__ == '__main__':
    fc = FlightController()
    fc.ascend(1000)
    fc.set_speed(250)
    fc.change_direction('E')
    fc.descend(500)
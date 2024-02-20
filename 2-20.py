from controller import Robot, Keyboard

# Initialize the robot and timestep
robot = Robot()
timestep = int(robot.getBasicTimeStep())

# Initialize motors
m1_motor = robot.getDevice("m1_motor")
m1_motor.setPosition(float('inf'))
m1_motor.setVelocity(0)
m2_motor = robot.getDevice("m2_motor")
m2_motor.setPosition(float('inf'))
m2_motor.setVelocity(0)
m3_motor = robot.getDevice("m3_motor")
m3_motor.setPosition(float('inf'))
m3_motor.setVelocity(0)
m4_motor = robot.getDevice("m4_motor")
m4_motor.setPosition(float('inf'))
m4_motor.setVelocity(0)

# Initialize keyboard
keyboard = Keyboard()
keyboard.enable(timestep)

# Define the step size for velocity change
step_size = 1.0

# Set initial velocities
    vx = 0
    vy = 0
    vz = 0
    yaw_rate = 0

# Main control loop
while robot.step(timestep) != -1:
    key = keyboard.getKey()

    
    # Interpret keyboard commands
    if key == Keyboard.UP:
        vx += step_size  # Increase forward velocity
    elif key == Keyboard.DOWN:
        vx -= step_size  # Decrease forward velocity
    elif key == Keyboard.RIGHT:
        yaw_rate -= step_size  # Increase clockwise yaw rate
    elif key == Keyboard.LEFT:
        yaw_rate += step_size  # Increase counterclockwise yaw rate
    elif key == ord('W'):
        vz += step_size  # Increase ascending velocity
    elif key == ord('S'):
        vz -= step_size  # Increase descending velocity

    # Set motor velocities based on keyboard commands
    m1_motor.setVelocity(vx - vy - yaw_rate + vz)
    m2_motor.setVelocity((vx + vy + yaw_rate + vz)*-1)
    m3_motor.setVelocity(-vx + vy - yaw_rate + vz)
    m4_motor.setVelocity((-vx - vy + yaw_rate + vz)*-1)

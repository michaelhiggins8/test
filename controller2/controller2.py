from controller import Robot,Motor,Keyboard

robot = Robot()
timestep = int(robot.getBasicTimeStep())


# make motors
motor1 = robot.getDevice("m1_motor")  
motor2 = robot.getDevice("m2_motor")  
motor3 = robot.getDevice("m3_motor")  
motor4 = robot.getDevice("m4_motor")  

# Set motor position to make the drone take off
motor1.setPosition(float('inf'))
motor2.setPosition(float('inf'))
motor3.setPosition(float('inf'))
motor4.setPosition(float('inf'))

# initiate motor speed
velocity = 2
motor1.setVelocity(velocity)
motor2.setVelocity(velocity)
motor3.setVelocity(velocity)
motor4.setVelocity(velocity)
i = 0
goingUp = True
keyboard = Keyboard()
keyboard.enable(timestep)
while robot.step(timestep) != -1:
    
    command = keyboard.getKey()
    if command == ord('A'):
        print("A")
    elif command == ord('B'):
        print("B")
    elif command == ord('C'):
        print("C")
    elif command == ord('D'):
        print("D")
    elif command == ord('E'):
        print("E")
    
    
 
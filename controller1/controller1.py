from controller import Robot,Motor

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
while robot.step(timestep) != -1:
    
    motor1.setVelocity(-1* i)
    motor2.setVelocity(i)
    motor3.setVelocity(-1 * i)
    motor4.setVelocity(i)
    
    if goingUp == True:
        i +=1
    elif goingUp == False:
        i -=1
    if i >=65:
        goingUp = False
    if i <= -1:
        goingUp = True
    
    print(i)
    
    
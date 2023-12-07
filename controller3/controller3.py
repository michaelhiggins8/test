from controller import Robot,Motor,Keyboard

robot = Robot()
timestep = int(robot.getBasicTimeStep())
velocity = 55.37
bladeSpeed = velocity
tiltDifference = 1.000001
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
velocity = 55.37
motor1.setVelocity( -1 * velocity)
motor2.setVelocity(velocity)
motor3.setVelocity( -1 * velocity)
motor4.setVelocity(velocity)
i = 0
goingUp = True
keyboard = Keyboard()
keyboard.enable(timestep)
while robot.step(timestep) != -1:
    
    command = keyboard.getKey()
    if command == Keyboard.UP:
        motor1.setVelocity(-1* bladeSpeed * tiltDifference)
        motor2.setVelocity(bladeSpeed * tiltDifference)
        motor3.setVelocity( -1 * bladeSpeed)
        motor4.setVelocity(bladeSpeed)
        print("forward")
    elif command == Keyboard.LEFT:
        motor1.setVelocity(-1* bladeSpeed * tiltDifference)
        motor2.setVelocity(bladeSpeed)
        motor3.setVelocity(-1 *  bladeSpeed)
        motor4.setVelocity(bladeSpeed * tiltDifference)
        print("left")
    elif command == Keyboard.RIGHT:
        motor1.setVelocity(-1 * bladeSpeed)
        motor2.setVelocity(bladeSpeed * tiltDifference)
        motor3.setVelocity(-1 * bladeSpeed * tiltDifference)
        motor4.setVelocity(bladeSpeed)
        print("right")
    elif command ==Keyboard.DOWN:
        motor1.setVelocity(-1 * bladeSpeed)
        motor2.setVelocity(bladeSpeed)
        motor3.setVelocity(-1 * bladeSpeed * tiltDifference)
        motor4.setVelocity(bladeSpeed * tiltDifference)
        print("back")
    
   
        
   
    
    
 
    
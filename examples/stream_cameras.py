#!/usr/bin/env python

import os
import time
from datetime import datetime
import cv2
import numpy as np
import rerun as rr
import torch
import zmq
from lerobot.common.robots.lekiwi import LeKiwiClient, LeKiwiClientConfig
from lerobot.common.utils.visualization_utils import _init_rerun
from lerobot.common.constants import OBS_IMAGES

def main():
    # Create output directory for saved images
    output_dir = "outputs/camera_images"
    os.makedirs(output_dir, exist_ok=True)
    
    # Create client configuration
    robot_config = LeKiwiClientConfig(
        remote_ip="192.168.86.29",
        id="rosey",
        # Increase timeouts for debugging
        polling_timeout_ms=1000,
        connect_timeout_s=10
    )

    # Create and connect to robot
    print(f"Connecting to LeKiwi host at {robot_config.remote_ip}...")
    robot = LeKiwiClient(robot_config)
    
    try:
        robot.connect()
        print("Successfully connected to LeKiwi host!")
    except zmq.error.ZMQError as e:
        print(f"ZMQ Error: {e}")
        print("Make sure the LeKiwi host is running on the remote machine")
        return
    except Exception as e:
        print(f"Connection error: {e}")
        return

    # Initialize rerun for visualization
    print("Initializing Rerun viewer...")
    _init_rerun("LeKiwi Camera Stream")
    print("Rerun viewer ready - you should see it in your browser or desktop app")

    try:
        print("\nWaiting for camera streams...")
        while True:
            try:
                # Get observations from the robot (includes camera frames)
                obs = robot.get_observation()
                if obs is None:
                    print("No observation received from host")
                    time.sleep(1)  # Wait longer when no data
                    continue

                # Print what we received (only first time)
                if not hasattr(main, "_printed_first_obs"):
                    print("\nReceived first observation with keys:", obs.keys())
                    print("\nFull observation data:")
                    for key, value in obs.items():
                        if isinstance(value, np.ndarray):
                            print(f"{key}: numpy array with shape {value.shape} and dtype {value.dtype}")
                        else:
                            print(f"{key}: {type(value)} = {value}")
                    main._printed_first_obs = True

                # Get the camera frames
                front_frame = obs.get("observation.images.front")
                wrist_frame = obs.get("observation.images.wrist")
                
                if not hasattr(main, "_printed_cameras"):
                    print("\nCamera data:")
                    if front_frame is not None:
                        print(f"  front: shape={front_frame.shape}, dtype={front_frame.dtype}")
                    else:
                        print("  front: None")
                    if wrist_frame is not None:
                        print(f"  wrist: shape={wrist_frame.shape}, dtype={wrist_frame.dtype}")
                    else:
                        print("  wrist: None")
                    main._printed_cameras = True

                # Process and display camera frames
                if front_frame is not None:
                    # Convert PyTorch tensor to numpy array
                    if isinstance(front_frame, torch.Tensor):
                        front_frame = front_frame.cpu().numpy()
                    # Log to rerun viewer
                    rr.log("camera/front", rr.Image(front_frame))
                    # Save image to disk
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    filename = f"front_{timestamp}.jpg"
                    filepath = os.path.join(output_dir, filename)
                    cv2.imwrite(filepath, front_frame)
                
                if wrist_frame is not None:
                    # Convert PyTorch tensor to numpy array
                    if isinstance(wrist_frame, torch.Tensor):
                        wrist_frame = wrist_frame.cpu().numpy()
                    # Log to rerun viewer
                    rr.log("camera/wrist", rr.Image(wrist_frame))
                    # Save image to disk
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    filename = f"wrist_{timestamp}.jpg"
                    filepath = os.path.join(output_dir, filename)
                    cv2.imwrite(filepath, wrist_frame)

            except zmq.error.ZMQError as e:
                print(f"ZMQ Error while getting observation: {e}")
                time.sleep(1)
            except Exception as e:
                print(f"Error while getting observation: {e}")
                time.sleep(1)

            # Small sleep to prevent maxing out CPU
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nStopping camera streams...")
    finally:
        # Cleanup
        robot.disconnect()
        print("Disconnected from LeKiwi host")

if __name__ == "__main__":
    main()

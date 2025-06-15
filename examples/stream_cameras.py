#!/usr/bin/env python

import os
import time
from datetime import datetime
import cv2
import numpy as np
import rerun as rr
import torch
import zmq
from lerobot.common.constants import OBS_IMAGES, OBS_STATE
from lerobot.common.robots.lekiwi.config_lekiwi import LeKiwiClientConfig
from lerobot.common.robots.lekiwi.lekiwi_client import LeKiwiClient
from lerobot.common.utils.visualization_utils import _init_rerun

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
        frame_counter = 0  # Initialize frame counter
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
                    # Print state information
                    if OBS_STATE in obs:
                        print(f"\n{OBS_STATE}:")
                        for key, value in obs[OBS_STATE].items():
                            print(f"  {key}: {value}")
                    
                # Get the camera frames
                for key in obs:
                    if key.startswith(OBS_IMAGES):
                        frame = obs[key]
                        if isinstance(frame, np.ndarray) and frame is not None:
                            # Extract camera name from key (e.g. 'front' from 'observation.images.front')
                            cam_name = key.split('.')[-1]
                            
                            # Convert from RGB to BGR for OpenCV
                            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                            
                            # Save frame
                            frame_path = f"{output_dir}/{cam_name}_{frame_counter}.jpg"
                            cv2.imwrite(frame_path, frame_bgr)

                            # Show in rerun viewer (expects RGB)
                            rr.log_image(f"cameras/{cam_name}", frame)
                            rr.log_text(f"cameras/{cam_name}/path", frame_path)

                frame_counter += 1

                if not hasattr(main, "_printed_cameras"):
                    print("\nCamera data:")
                    for key in obs:
                        if key.startswith(OBS_IMAGES):
                            if isinstance(obs[key], np.ndarray):
                                print(f"  {key.split('.')[-1]}: shape={obs[key].shape}, dtype={obs[key].dtype}")
                            else:
                                print(f"  {key.split('.')[-1]}: {type(obs[key])}")
                    main._printed_cameras = True
                    main._printed_first_obs = True



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

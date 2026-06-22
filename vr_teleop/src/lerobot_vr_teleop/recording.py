# Copyright 2024 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Reusable LeRobot dataset recording helpers for VR teleop.

The feature spec is derived from ``robot.action_features`` (the single source of
truth in :class:`~lerobot.robots.xlerobot.XLerobot`) filtered to the enabled arms,
rather than hand-written name lists -- so the recorded ``action`` / ``observation.state``
dimensions cannot silently drift from the control loop's ``enable_left`` setting.
"""

from __future__ import annotations

import logging
import queue
import threading

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.datasets.utils import hw_to_dataset_features
from lerobot.utils.constants import OBS_STR

logger = logging.getLogger(__name__)


def arm_state_keys(robot, enable_left: bool) -> list[str]:
    """Ordered ``*_arm_*.pos`` keys recorded for the enabled arms (left then right)."""
    keys = []
    if enable_left:
        keys += [k for k in robot.action_features if k.startswith("left_arm_")]
    keys += [k for k in robot.action_features if k.startswith("right_arm_")]
    return keys


def make_xlerobot_dataset(
    robot,
    *,
    repo_id: str,
    root: str,
    fps: int,
    enable_left: bool,
    image_writer_processes: int = 10,
    image_writer_threads: int = 5,
) -> LeRobotDataset:
    """Create a LeRobot dataset whose action/state features match the enabled arms."""
    names = arm_state_keys(robot, enable_left)
    dim = len(names)
    features = {
        "action": {"dtype": "float32", "shape": (dim,), "names": names},
        "observation.state": {"dtype": "float32", "shape": (dim,), "names": names},
    }
    features = {**features, **hw_to_dataset_features(robot._cameras_ft, OBS_STR)}

    dataset = LeRobotDataset.create(
        repo_id=repo_id,
        root=root,
        features=features,
        fps=fps,
        image_writer_processes=image_writer_processes,
        image_writer_threads=image_writer_threads,
    )
    return dataset


def _saver_worker(dataset, frame_queue, shutdown_event, saving_event, episode_len, n_episodes, push_to_hub):
    try:
        dataset.meta.update_chunk_settings(video_files_size_in_mb=0.001)
        frame_nr = 0
        episode = 0
        while not shutdown_event.is_set():
            try:
                frame = frame_queue.get(timeout=1)
            except queue.Empty:
                continue

            dataset.add_frame(frame)
            frame_nr += 1

            if frame_nr >= episode_len:
                logger.info("Finishing episode %d", episode)
                saving_event.set()
                dataset.save_episode()
                dataset.image_writer.wait_until_done()
                saving_event.clear()
                frame_nr = 0
                episode += 1
                if episode >= n_episodes:
                    logger.info("Reached %d episodes; stopping recording.", n_episodes)
                    shutdown_event.set()
                    break
    except Exception as e:
        logger.error("Error in dataset saving worker: %s", e, exc_info=True)
    finally:
        try:
            dataset.image_writer.wait_until_done()
            dataset.save_episode()
            if push_to_hub:
                dataset.push_to_hub()
        except Exception as e:
            logger.warning("Final dataset flush failed: %s", e)


def start_saver(
    dataset,
    frame_queue: "queue.Queue",
    shutdown_event: threading.Event,
    saving_event: threading.Event,
    *,
    episode_len: int,
    n_episodes: int,
    push_to_hub: bool = True,
) -> threading.Thread:
    """Spawn (and start) the background dataset-saving thread."""
    thread = threading.Thread(
        target=_saver_worker,
        args=(dataset, frame_queue, shutdown_event, saving_event, episode_len, n_episodes, push_to_hub),
        daemon=False,
    )
    thread.start()
    return thread

{'observation.state': array([-12.144703, -99.351555, 100.,  38.07082,   2.0268621,
                             4.895105,   0.,   0.,   0.], dtype=float32),
 'observation.images.front': tensor([[[1,   1,   1],
                                     [1,   1,   1],
                                      [1,   1,   1],
                                      ...,
                                      [64,  67,  58],
                                      [73,  73,  67],
                                      [71,  71,  65]],

                                     [[1,   1,   1],
                                      [1,   1,   1],
                                      [1,   1,   1],
                                      ...,
                                      [65,  68,  59],
                                      [73,  73,  67],
                                      [71,  71,  65]],

                                     [[1,   1,   1],
                                      [1,   1,   1],
                                      [1,   1,   1],
                                      ...,
                                      [67,  70,  61],
                                      [74,  75,  66],
                                      [72,  73,  64]],

                                     ...,

                                     [[0,   0,   0],
                                      [0,   1,   0],
                                      [0,   1,   1],
                                      ...,
                                      [156, 172, 155],
                                      [152, 168, 151],
                                      [151, 170, 151]],

                                     [[0,   0,   1],
                                      [0,   1,   0],
                                      [0,   1,   2],
                                      ...,
                                      [153, 169, 152],
                                      [151, 167, 150],
                                      [154, 170, 153]],

                                     [[0,   0,   1],
                                      [0,   0,   1],
                                      [0,   1,   2],
                                      ...,
                                      [152, 165, 151],
                                      [150, 166, 149],
                                      [155, 171, 154]]], dtype=torch.uint8),
 'observation.images.wrist': tensor([[[2,   0,   0],
                                     [2,   0,   0],
                                      [2,   0,   0],
                                      ...,
                                      [181, 192, 200],
                                      [181, 192, 200],
                                      [182, 193, 201]],

                                     [[2,   0,   0],
                                      [2,   0,   0],
                                      [2,   0,   0],
                                      ...,
                                      [181, 192, 200],
                                      [181, 192, 200],
                                      [181, 192, 200]],

                                     [[2,   0,   0],
                                      [2,   0,   0],
                                      [2,   0,   0],
                                      ...,
                                      [182, 191, 200],
                                      [182, 191, 200],
                                      [182, 191, 200]],

                                     ...,

                                     [[93, 129,  93],
                                      [87, 125,  89],
                                      [84, 121,  87],
                                      ...,
                                      [34, 128,  33],
                                      [38, 132,  37],
                                      [36, 130,  35]],

                                     [[22, 136,  19],
                                      [24, 138,  21],
                                      [25, 139,  22],
                                      ...,
                                      [13, 148,  10],
                                      [12, 147,   9],
                                      [10, 145,   7]],

                                     [[4, 155,   0],
                                      [3, 154,   0],
                                      [0, 152,   0],
                                      ...,
                                      [0, 153,   0],
                                      [2, 156,   0],
                                      [2, 156,   0]]], dtype=torch.uint8)}

{'action': {'dtype': 'float32', 'shape': (9,),
            'names': ['arm_shoulder_pan.pos', 'arm_shoulder_lift.pos', 'arm_elbow_flex.pos', 'arm_wrist_flex.pos', 'arm_wrist_roll.pos', 'arm_gripper.pos', 'x.vel', 'y.vel', 'theta.vel']},
    'observation.state': {'dtype': 'float32', 'shape': (9,),
                          'names': ['arm_shoulder_pan.pos', 'arm_shoulder_lift.pos', 'arm_elbow_flex.pos', 'arm_wrist_flex.pos', 'arm_wrist_roll.pos', 'arm_gripper.pos', 'x.vel', 'y.vel', 'theta.vel']},
    'observation.images.front': {'dtype': 'video', 'shape': (480, 640, 3), 'names': ['height', 'width', 'channels']},
    'observation.images.wrist': {'dtype': 'video', 'shape': (640, 480, 3), 'names': ['height', 'width', 'channels']},
    'timestamp': {'dtype': 'float32', 'shape': (1,), 'names': None},
    'frame_index': {'dtype': 'int64', 'shape': (1,), 'names': None},
    'episode_index': {'dtype': 'int64', 'shape': (1,), 'names': None},
    'index': {'dtype': 'int64', 'shape': (1,), 'names': None},
    'task_index': {'dtype': 'int64', 'shape': (1,), 'names': None}}



FIXME: 
Add this to dataset_stats:

('observation.images.observation.images.front', PolicyFeature(type=<FeatureType.VISUAL: 'VISUAL'>, shape=(3, 640, 480))), 
('observation.images.observation.images.wrist', PolicyFeature(type=<FeatureType.VISUAL: 'VISUAL'>, shape=(3, 640, 480)))]


The norm mapping for ACT is this but it is different for SMOLVLA

normalization_mapping: dict[str, NormalizationMode] = field(
default_factory=lambda: {
    "VISUAL": NormalizationMode.MEAN_STD,
    "STATE": NormalizationMode.MEAN_STD,
    "ACTION": NormalizationMode.MEAN_STD,
}
)

{STATE: {                min: [-1.0, -1.0, -1.0, -1.0, -1.0, -1.0],                max: [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],                mean: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],                std: [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],                count: [1]            },            ACTION: {                min: [-1.0, -1.0, -1.0, -1.0, -1.0, -1.0],                max: [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],                mean: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],                std: [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],                count: [1]            }        }

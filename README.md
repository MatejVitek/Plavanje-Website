# Project
This is a signup sheet for FRI's swimming program.

# Administration

## Configuration
The configuration can be changed in `config.yaml`. Make sure not to delete or rename any of the keys, you should only change the values. In there, you can change the lesson times, the signup times, the lesson capacity, and the algorithm used to select the participants.

If the file gets corrupted, below is a default configuration for reference:

```
lesson:
  weekday: thursday
  time: '14:30'
  capacity: 6
  cancel_deadline_hours: 4

signup_window:
  weekday: friday
  start: '10:00'
  end: '11:00'

email:
  allowed_domains:
    - fri.uni-lj.si
    - fe.uni-lj.si

algorithm:
  name: LPV             # LPV (least previous visits), random, weighted_random, or FCFS (first come first serve)
  weight_exponent: 1.0  # Only used for weighted_random algorithm. 0.0 = uniform random; 0.5-1.0 = random but weighted with number of previous visits; very high (e.g. 99) = LPV.
```

## Resetting
To reset the app (such as for when the new school year starts), delete the files in the `data` directory.
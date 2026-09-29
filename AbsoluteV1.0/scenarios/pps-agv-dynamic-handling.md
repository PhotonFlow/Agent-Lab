The pps source is the pallet perception stack on an AGV. The user is the vehicle's dynamic handling process: it needs a pallet pose while the scene can still change. The outputs that matter are the pallet pose, the pallet width, height, and depth in metres, and which detected pallets are sent through stage 2 versus marked deferred.

output: pose pose_error_m minimize 0.001 0
output: dimensions dimension_error_m minimize 0.001 0
output: selection selection_error minimize 0.001 0
output: scenario scenario_error minimize 0.001 0
protected: latency_ms minimize 5

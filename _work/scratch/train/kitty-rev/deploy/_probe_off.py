import json, sys
sys.path.insert(0, ".")
import autodl_power as P
for path in ("/instance/power_off", "/instance/shutdown", "/instance/instance/power_off"):
    j = P.api(path, {"instance_uuid": "00000000-0000-0000-0000-000000000000"})
    print(f"{path:<34} {j.get('code')}  {str(j.get('msg'))[:60]}")

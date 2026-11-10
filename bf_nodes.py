import json
from amazon_api import CreatorsAPI
api=CreatorsAPI.from_env("cazachollos0c-21")
ids="6198073031 6198055031 1703496031 2454134031 2665403031 599371031 4772051031 599392031 667050031 1571260031 599386031 5512277031 12472656031 3677431031 599383031 1571258031 1571259031 1571261031 1703495031 2454133031 2665402031 599370031 599391031 667049031 599385031 599382031 5512276031 12472499031 3677430031 4772050031".split()
def anc(n):
    out=[];a=n.get("ancestor")
    while a: out.append(a.get("displayName") or a.get("contextFreeName")); a=a.get("ancestor")
    return " < ".join(out)
for i in range(0,len(ids),10):
    try:
        d=api.call("getBrowseNodes",{"browseNodeIds":ids[i:i+10],"languagesOfPreference":["es_ES"],"resources":["browseNodes.ancestor"]})
    except Exception as e:
        print("ERR",e); continue
    found=d.get("browseNodesResult",{}).get("browseNodes",[])
    for n in found: print("NODE",n.get("id"),"|",n.get("displayName"),"|",n.get("contextFreeName"),"| root:",n.get("isRoot"),"|",anc(n))
    for e in d.get("errors",[]) or []: print("E",json.dumps(e)[:200])

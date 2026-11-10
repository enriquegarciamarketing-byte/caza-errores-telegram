import json, os, urllib.request, urllib.parse
tok=os.environ["TELEGRAM_BOT_TOKEN"]; chat=json.load(open("config.json"))["amazon_channel"]["chat_id"]
data=urllib.parse.urlencode({"chat_id":chat,"message_id":439,"caption":open("bf_caption.html").read(),"parse_mode":"HTML"}).encode()
try:
    r=json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/editMessageCaption",data=data,timeout=30))
except urllib.error.HTTPError as e:
    r={"error":e.read().decode()[:300]}
res=r.get("result") or {}
print("EDIT", r.get("ok"), r.get("error",""))
for e in res.get("caption_entities",[]):
    if e.get("type")=="text_link":
        t=res["caption"].encode("utf-16-le")[e["offset"]*2:(e["offset"]+e["length"])*2].decode("utf-16-le")
        print("LINK",t,"->",e["url"][:70],"... tag ok:",e["url"].endswith("tag=cazachollos0c-21"))

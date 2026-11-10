import re, html, json, os, urllib.request, urllib.parse
t=html.unescape(open("p.html",encoding="utf-8",errors="ignore").read()).replace('\\"','"')
pairs=dict((v,l) for l,v in re.findall(r'\{"label":\[\{"text":"([^"]+)"\}\],"isSelected":(?:true|false),"isDisabled":(?:true|false),"value":"(\d+)"\}',t))
cap=open("bf_caption.html").read()
bad=0
for href,name in re.findall(r'<a href="([^"]+)">([^<]+)</a>',cap):
    m=re.search(r'departments%255C%2522%253A%255B%255C%2522(\d+)%255C',href)
    if not m: print("CHK",name,"-> general"); continue
    lab=pairs.get(m.group(1),"NO ESTÁ EN LA PÁGINA"); print("CHK",name,"->",m.group(1),"=",lab)
    if lab=="NO ESTÁ EN LA PÁGINA": bad+=1
assert pairs.get("1571260031")=="Jardín"
tok=os.environ["TELEGRAM_BOT_TOKEN"]; chat=json.load(open("config.json"))["amazon_channel"]["chat_id"]
data=urllib.parse.urlencode({"chat_id":chat,"message_id":439,"caption":cap,"parse_mode":"HTML"}).encode()
r=json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/editMessageCaption",data=data,timeout=30))
res=r["result"]
for e in res.get("caption_entities",[]):
    if e.get("type")=="text_link":
        txt=res["caption"].encode("utf-16-le")[e["offset"]*2:(e["offset"]+e["length"])*2].decode("utf-16-le")
        if txt=="Jardín": print("JARDIN",e["url"])
print("EDIT",r["ok"],"bad",bad)

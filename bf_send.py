import json, os, urllib.request, uuid
tok=os.environ["TELEGRAM_BOT_TOKEN"]; chat=json.load(open("config.json"))["amazon_channel"]["chat_id"]
cap=open("bf_caption.html").read(); img=open("images/manual/black-friday-2026.png","rb").read()
b=uuid.uuid4().hex; parts=[]
for k,v in {"chat_id":chat,"caption":cap,"parse_mode":"HTML"}.items():
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
parts.append(f'--{b}\r\nContent-Disposition: form-data; name="photo"; filename="bf.png"\r\nContent-Type: image/png\r\n\r\n'.encode()+img+b"\r\n")
body=b"".join(parts)+f"--{b}--\r\n".encode()
req=urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendPhoto",data=body,headers={"Content-Type":f"multipart/form-data; boundary={b}"})
r=json.load(urllib.request.urlopen(req,timeout=60)); print("OK" if r.get("ok") else r, chat, r.get("result",{}).get("message_id"))

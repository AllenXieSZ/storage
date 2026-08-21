#!/usr/bin/env python3
# 批量灌 OpenCart 商品 (压测前准备数据): 商品记录写 Aurora + 图片下载到 image 目录
# 用法: DB_HOST=... DB_PASS=... python3 loadtest_seed_products.py [商品数量]
# 环境变量: DB_HOST / DB_USER(默认admin) / DB_PASS / DB(默认opencart) / PFX(默认oc_)
#           IMG_DIR(默认 /var/www/html/image/catalog/loadtest)
import pymysql, os, random, subprocess, sys

DB_HOST = os.environ["DB_HOST"]              # 例: opencart-aurora.cluster-xxx.us-east-2.rds.amazonaws.com
DB_USER = os.environ.get("DB_USER", "admin")
DB_PASS = os.environ["DB_PASS"]              # 从环境变量传, 不要硬编码
DB      = os.environ.get("DB", "opencart")
PFX     = os.environ.get("PFX", "oc_")
IMG_DIR = os.environ.get("IMG_DIR", "/var/www/html/image/catalog/loadtest")
IMG_REL = os.environ.get("IMG_REL", "catalog/loadtest")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 300

os.makedirs(IMG_DIR, exist_ok=True)

BRANDS = ["Acme","Nova","Zenith","Apex","Orion","Pulse","Vertex","Lumen","Astra","Flux"]
CATEGORIES = {
    20:["Desktop PC","Workstation","Mini PC","Gaming Tower"],
    18:["Laptop","Notebook","Ultrabook","Gaming Laptop"],
    33:["DSLR Camera","Mirrorless Camera","Action Cam","Webcam"],
    28:["Monitor 27in","Monitor 32in","Curved Display","4K Monitor"],
    34:["MP3 Player","Hi-Res Player","Portable DAC"],
    29:["Wireless Mouse","Gaming Mouse","Trackball","Ergo Mouse"],
}
ADJ = ["Pro","Max","Ultra","Air","Lite","Plus","Elite","Prime","X","S"]

conn = pymysql.connect(host=DB_HOST,user=DB_USER,password=DB_PASS,database=DB,charset="utf8mb4",autocommit=False)
cur = conn.cursor()

created = 0
for i in range(N):
    cat = random.choice(list(CATEGORIES.keys()))
    base = random.choice(CATEGORIES[cat])
    brand = random.choice(BRANDS); adj = random.choice(ADJ)
    name = f"{brand} {base} {adj} {random.randint(100,999)}"
    sku = f"LT-{cat}-{i:04d}"
    model = f"MDL{random.randint(10000,99999)}"
    price = round(random.uniform(29, 2999), 2)
    qty = random.randint(10, 500)
    img_name = f"lt_{i:04d}.jpg"
    img_path = f"{IMG_DIR}/{img_name}"
    if not os.path.exists(img_path):
        subprocess.run(["curl","-sL","-o",img_path,f"https://picsum.photos/seed/{sku}/500/500"],timeout=30)
        if not os.path.exists(img_path) or os.path.getsize(img_path) < 1000:
            subprocess.run(["curl","-sL","-o",img_path,f"https://dummyimage.com/500x500/2e9e5b/fff.jpg&text={sku}"],timeout=20)
    img_db = f"{IMG_REL}/{img_name}"
    cur.execute(f"""INSERT INTO {PFX}product
      (model,quantity,stock_status_id,image,price,tax_class_id,status,date_available,date_added,date_modified,weight,length,width,height,length_class_id,weight_class_id,subtract,minimum,sort_order,shipping)
      VALUES (%s,%s,7,%s,%s,0,1,CURDATE(),NOW(),NOW(),0,0,0,0,1,1,1,1,0,1)""",
      (model,qty,img_db,price))
    pid = cur.lastrowid
    try:
        cur.execute(f"INSERT INTO {PFX}product_code (product_id,type,code) VALUES (%s,'sku',%s)",(pid,sku))
    except Exception:
        pass
    cur.execute(f"""INSERT INTO {PFX}product_description
      (product_id,language_id,name,description,tag,meta_title,meta_description,meta_keyword)
      VALUES (%s,1,%s,%s,%s,%s,%s,%s)""",
      (pid,name,f"<p>{name} - high quality {base.lower()} by {brand}. SKU {sku}.</p>","",name,name,base))
    cur.execute(f"INSERT INTO {PFX}product_to_category (product_id,category_id) VALUES (%s,%s)",(pid,cat))
    cur.execute(f"INSERT INTO {PFX}product_to_store (product_id,store_id) VALUES (%s,0)",(pid,))
    cur.execute(f"INSERT INTO {PFX}product_to_layout (product_id,store_id,layout_id) VALUES (%s,0,0)",(pid,))
    try:
        cur.execute(f"INSERT INTO {PFX}seo_url (store_id,language_id,key,value,keyword) VALUES (0,1,'product_id',%s,%s)",(pid,f"lt-{sku.lower()}"))
    except Exception:
        pass
    created += 1
    if created % 50 == 0:
        conn.commit(); print(f"committed {created}...", flush=True)

conn.commit()
print(f"DONE: created {created} products")
cur.close(); conn.close()

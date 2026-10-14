# unthrottled: P procs each create 1MiB files in its own dir for D seconds; prints files/s
import os,sys,time,multiprocessing as mp
root,P,D,tag=sys.argv[1],int(sys.argv[2]),float(sys.argv[3]),sys.argv[4]
def w(p,q):
    d=f"{root}/{tag}/p{p}"; os.makedirs(d,exist_ok=True); b=os.urandom(1<<20); n=0; end=time.time()+D
    while time.time()<end:
        fd=os.open(f"{d}/f{n}",os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o644); os.write(fd,b); os.close(fd); n+=1
    q.put(n)
q=mp.Queue(); ps=[mp.Process(target=w,args=(p,q)) for p in range(P)]; [x.start() for x in ps]; [x.join() for x in ps]
t=sum(q.get() for _ in ps); print(tag,"files/s",t/D)

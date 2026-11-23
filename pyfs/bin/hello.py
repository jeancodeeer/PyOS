# A tiny program: run it as a process with  start('hello', 'mundo')
import sys
from kernel import proc

me = proc.current()
print("hola %s, soy el proceso %d (padre %d)" % (" ".join(me.argv[1:]) or "mundo", me.pid, me.ppid))

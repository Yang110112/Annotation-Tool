import hashlib
pwd = "770258"
h = hashlib.sha256(pwd.encode("utf-8")).hexdigest()
print(h)

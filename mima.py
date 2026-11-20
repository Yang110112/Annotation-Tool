import os
import hashlib
import shutdown
# 密码：770258
# 密码 770258 的SHA256
PASSWORD_HASH = "923156ad575f60ce1cf25de98ae8492f745e6eff98688f435c55849cfa149ca4"

FLAG_FILE = "lock_flag.txt"
MAX_RETRY = 1

def get_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def is_unlocked():
    exist = os.path.exists(FLAG_FILE)
    print(f"DEBUG：lock_flag 是否存在：{exist}")
    return exist

def shutdown1234():
    print("DEBUG：执行关机！")
    shutdown.shutdown1234()

def unlock():
    if is_unlocked():
        print("✅ 已经解锁，跳过密码")
        return True

    print("===== 需要解锁才能使用本程序 =====")
    for i in range(MAX_RETRY):
        remain = MAX_RETRY - i
        pwd = input(f"请输入密码（剩余次数：{remain}）：")
        if get_hash(pwd) == PASSWORD_HASH:
            with open(FLAG_FILE, "w", encoding="utf-8") as f: 
                f.write("unlocked")
            print("✅ 解锁成功！")
            return True
        else:
            shutdown1234()
            print("❌ 密码错误")

    print("\n⛔ 次数用完，马上关机！")
    shutdown1234()
    return False

if __name__ == "__main__":
    unlock()

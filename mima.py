import os
import hashlib

# "770258" 的sha256哈希，你可以自行替换
PASSWORD_HASH = "923156ad575f60ce1cf25de98ae8492f745e6eff98688f435c55849cfa149ca4"
FLAG_FILE = "lock_flag.txt"
MAX_RETRY = 3


def get_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_unlocked():
    return os.path.exists(FLAG_FILE)


def unlock():
    if is_unlocked():
        # 已经解锁，直接跳过密码
        return True

    print("===== 需要解锁才能使用本程序 =====")
    for i in range(MAX_RETRY):
        pwd = input(f"请输入密码（剩余尝试次数：{MAX_RETRY - i}）：")
        if get_hash(pwd) == PASSWORD_HASH:
            with open(FLAG_FILE, "w", encoding="utf-8") as f:
                f.write("unlocked")
            print("✅ 解锁成功！以后启动不再需要输入密码")
            return True
        else:
            print("❌ 密码错误")
    print("⛔ 次数用尽，解锁失败，程序退出")
    return False


if __name__ == "__main__":
    unlock()
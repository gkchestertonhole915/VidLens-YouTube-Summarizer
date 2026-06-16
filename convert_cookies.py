"""把 Cookie-Editor 导出的 JSON cookies 转成 yt-dlp 用的 Netscape cookies.txt。
用法: python convert_cookies.py cookies.json cookies.txt
"""
import json
import sys


def convert(json_path: str, txt_path: str):
    data = json.loads(open(json_path, encoding="utf-8").read())
    lines = [
        "# Netscape HTTP Cookie File",
        "# Converted by VidLens convert_cookies.py",
        "",
    ]
    for c in data:
        domain = c["domain"]
        # httpOnly cookie 在 Netscape 格式里 domain 前加 #HttpOnly_ 前缀
        domain_field = ("#HttpOnly_" + domain) if c.get("httpOnly") else domain
        include_sub = "TRUE" if not c.get("hostOnly") else "FALSE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        # 会话 cookie 无过期时间，记 0
        exp = int(c["expirationDate"]) if c.get("expirationDate") else 0
        name = c["name"]
        value = c["value"]
        lines.append("\t".join([domain_field, include_sub, path, secure, str(exp), name, value]))
    open(txt_path, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print(f"已写出 {txt_path}，共 {len(data)} 条 cookie")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "cookies.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "cookies.txt"
    convert(src, dst)

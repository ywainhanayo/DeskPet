"""公开版 .petpack v2 格式：zlib 压缩后做可逆混淆。

布局为 PETP 魔数、1 字节版本、2 字节条目数，随后每个条目依次存
UTF-8 名称长度和名称、压缩/原始长度、混淆后的压缩数据。所需条目是
meta/name、meta/character_id、meta/hd 和至少一帧；可带 persona.json。
算法和种子随源码公开，只能防止直接解压和随手查看，不能保护真正保密的素材。
"""

import hashlib
import json
import re
import struct
import zlib

MAGIC = b"PETP"
VERSION = 2
MAX_ENTRY = 32 * 1024 * 1024   # 单条目解压上限(防异常/恶意包把内存吃爆)
MAX_PACK = 64 * 1024 * 1024
MAX_ENTRIES = 64
OBFUSCATION_SEED = b"DeskPet petpack v2 public obfuscation"
STREAM_CHUNK = 64 * 1024


class PackError(Exception):
    """包损坏/版本不对/截断。调用方(引擎)捕获后跳过该包即可。"""


def valid_character_id(value):
    return isinstance(value, str) and re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{0,63}", value) is not None


def _obfuscate(entry_name: str, data: bytes) -> bytes:
    """同一算法用于混淆和还原；公开种子不是保密密钥。"""
    seed = hashlib.sha256(OBFUSCATION_SEED + b"\x00"
                          + entry_name.encode("utf-8")).digest()
    output = bytearray()
    for offset in range(0, len(data), STREAM_CHUNK):
        chunk = data[offset:offset + STREAM_CHUNK]
        counter = (offset // STREAM_CHUNK).to_bytes(4, "little")
        stream = hashlib.shake_256(seed + counter).digest(len(chunk))
        output.extend((int.from_bytes(chunk, "little")
                       ^ int.from_bytes(stream, "little"))
                      .to_bytes(len(chunk), "little"))
    return bytes(output)


def read_pack(data: bytes) -> dict:
    """解析 .petpack 字节 → {"name","hd","frames":{帧名:PNG 字节},"persona":dict|None}。
    任何问题抛 PackError。"""
    if data[:4] != MAGIC:
        raise PackError("不是皮肤包(魔数不符)")
    if len(data) < 7:
        raise PackError("文件截断")
    if len(data) > MAX_PACK:
        raise PackError("皮肤包超过大小上限")
    version = data[4]
    if version != VERSION:
        raise PackError(f"格式版本不支持({version})")
    (count,) = struct.unpack_from("<H", data, 5)
    if count > MAX_ENTRIES:
        raise PackError("皮肤包条目过多")
    pos = 7
    entries = {}
    for _ in range(count):
        if pos + 2 > len(data):
            raise PackError("文件截断(条目名长度)")
        (nl,) = struct.unpack_from("<H", data, pos)
        pos += 2
        if pos + nl + 8 > len(data):
            raise PackError("文件截断(条目头)")
        name = data[pos:pos + nl].decode("utf-8", "replace")
        pos += nl
        comp_len, raw_len = struct.unpack_from("<II", data, pos)
        pos += 8
        if comp_len > MAX_ENTRY or raw_len > MAX_ENTRY:
            raise PackError(f"条目 {name} 尺寸异常")
        comp = data[pos:pos + comp_len]
        pos += comp_len
        if len(comp) != comp_len:
            raise PackError("文件截断(条目数据)")
        try:
            decompressor = zlib.decompressobj()
            raw = decompressor.decompress(_obfuscate(name, comp), raw_len + 1)
        except zlib.error as e:
            raise PackError(f"条目 {name} 解压失败({e})") from e
        if (len(raw) != raw_len or not decompressor.eof
                or decompressor.unused_data or decompressor.unconsumed_tail):
            raise PackError(f"条目 {name} 长度或压缩流无效")
        if name in entries:
            raise PackError(f"重复条目 {name}")
        entries[name] = raw
    if pos != len(data):
        raise PackError("文件尾部有多余数据(被篡改或拼接)")

    name = entries.get("meta/name", b"").decode("utf-8", "replace").strip()
    if not name:
        raise PackError("缺少 meta/name")
    raw_id = entries.get("meta/character_id")
    if raw_id is None:
        raise PackError("缺少 meta/character_id")
    else:
        character_id = raw_id.decode("ascii", "replace")
        if not valid_character_id(character_id):
            raise PackError("角色 ID 不合法")
    hd = entries.get("meta/hd", b"0") == b"1"
    frames = {k.split("/", 1)[1]: v for k, v in entries.items()
              if k.startswith("frames/") and len(k) > len("frames/")}
    if not frames:
        raise PackError("包内没有任何帧")
    persona = None
    if "persona.json" in entries:
        try:
            persona = json.loads(entries["persona.json"].decode("utf-8"))
            if not isinstance(persona, dict):
                persona = None
            elif any(not isinstance(persona.get(key, ""), str)
                     for key in ("name", "user_title", "extra")):
                raise PackError("persona.json 字段必须是字符串")
        except (ValueError, UnicodeDecodeError):
            persona = None
    return {"name": name, "character_id": character_id, "hd": hd,
            "frames": frames, "persona": persona}

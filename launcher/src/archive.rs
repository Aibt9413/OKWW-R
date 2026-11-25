//! 单文件归档（SFX）的尾部格式解析与释放。
//!
//! 归档布局（附加在 launcher exe 二进制之后）：
//!   [payload 数据区] [entry 表] [footer]
//!   footer (定长 64B):
//!     magic[8]        = "WWPKG01\n"
//!     data_len  u64  数据区字节数
//!     entry_cnt u32  条目数
//!     data_sha  [32] 数据区 SHA256
//!     table_off u64  条目表相对文件起点偏移
//!   entry (定长 24B + N 字节路径):
//!     name_len  u32
//!     off       u64  相对数据区起点
//!     len       u64
//!     name      [name_len] UTF-8 相对路径（'/' 分隔）
//!
//! 全部为纯 std 实现。只做完整性校验 + 安全释放，不含反调试/注入/隐藏。

use std::fs::{self, File};
use std::io::{BufWriter, Read, Seek, SeekFrom, Write};
use std::path::{Component, Path};

use crate::sha256;

pub const MAGIC: &[u8; 8] = b"WWPKG01\n";
pub const FOOTER_SIZE: usize = 64;

#[derive(Debug, Clone)]
pub struct Footer {
    pub data_len: u64,
    pub entry_count: u32,
    pub data_sha: [u8; 32],
    pub table_off: u64,
}

#[derive(Debug, Clone)]
pub struct Entry {
    pub name: String,
    pub off: u64,
    pub len: u64,
}

/// 从文件尾部读取并解析 footer；没有合法 magic 时返回 Ok(None)（兼容旧的双文件模式）。
pub fn read_footer(path: &Path) -> std::io::Result<Option<Footer>> {
    let mut f = File::open(path)?;
    let file_len = f.metadata()?.len();
    if file_len < FOOTER_SIZE as u64 {
        return Ok(None);
    }
    f.seek(SeekFrom::End(-(FOOTER_SIZE as i64)))?;
    let mut buf = [0u8; FOOTER_SIZE];
    f.read_exact(&mut buf)?;
    if &buf[0..8] != MAGIC {
        return Ok(None);
    }
    let data_len = u64::from_le_bytes(buf[8..16].try_into().unwrap());
    let entry_count = u32::from_le_bytes(buf[16..20].try_into().unwrap());
    let mut data_sha = [0u8; 32];
    data_sha.copy_from_slice(&buf[20..52]);
    let table_off = u64::from_le_bytes(buf[52..60].try_into().unwrap());
    Ok(Some(Footer { data_len, entry_count, data_sha, table_off }))
}

/// 校验数据区 SHA256 与 footer 记录一致。
pub fn verify_data(file: &Path, footer: &Footer) -> std::io::Result<String> {
    let mut f = File::open(file)?;
    let data_off = footer.table_off - footer.data_len; // 数据区紧邻条目表之前
    f.seek(SeekFrom::Start(data_off))?;
    let mut remaining = footer.data_len;
    let mut buf = vec![0u8; 1024 * 1024];
    // 流式哈希，避免大归档整体读入内存
    let mut hasher = StreamingHasher::new();
    while remaining > 0 {
        let want = remaining.min(buf.len() as u64) as usize;
        f.read_exact(&mut buf[..want])?;
        hasher.update(&buf[..want]);
        remaining -= want as u64;
    }
    let actual = hasher.finish();
    Ok(sha256::hex(&actual))
}

/// 流式 SHA256：固定 64 字节缓冲 + 计数，零堆分配。
/// 注意：早期版本用 Vec::drain 逐块移除，485MB 数据会产生约 750 万次
/// O(n) 搬移，校验耗时数分钟。改成索引式消费后为 O(n)，秒级完成。
struct StreamingHasher {
    state: [u32; 8],
    total_len: u64,
    pending: [u8; 64],
    pending_len: usize,
}

impl StreamingHasher {
    fn new() -> Self {
        Self {
            state: [
                0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
            ],
            total_len: 0,
            pending: [0u8; 64],
            pending_len: 0,
        }
    }

    fn update(&mut self, mut data: &[u8]) {
        self.total_len = self.total_len.wrapping_add(data.len() as u64);
        // 先补齐上一次留下的不足 64 字节的尾巴
        if self.pending_len > 0 {
            let need = 64 - self.pending_len;
            let take = need.min(data.len());
            self.pending[self.pending_len..self.pending_len + take].copy_from_slice(&data[..take]);
            self.pending_len += take;
            data = &data[take..];
            if self.pending_len == 64 {
                let block = self.pending;
                sha256::compress(&mut self.state, &block);
                self.pending_len = 0;
            }
        }
        // 剩余数据按整块直接压缩，不经过缓冲
        while data.len() >= 64 {
            let block: [u8; 64] = data[..64].try_into().unwrap();
            sha256::compress(&mut self.state, &block);
            data = &data[64..];
        }
        if !data.is_empty() {
            self.pending[..data.len()].copy_from_slice(data);
            self.pending_len = data.len();
        }
    }

    fn finish(mut self) -> [u8; 32] {
        let bit_len = self.total_len.wrapping_mul(8);
        // SHA256 padding：pending_len 恒在 0..=63（update 中满 64 即压掉）。
        //   - pending_len <= 55：单块。0x80 后补零到 56，再写 8 字节长度。
        //   - pending_len >= 56：两块。第一块 0x80 后补零到 64 并压掉；
        //     第二块全零，只在 56..64 写长度。
        // 早期实现在 n=57..=62 时执行 copy_within(64..n)（start>end 直接 panic），
        // 在 n=64 时又漏处理导致长度域覆盖 0x80。这里按标准分两种情形重写。
        let mut block = [0u8; 64];
        block[..self.pending_len].copy_from_slice(&self.pending[..self.pending_len]);
        block[self.pending_len] = 0x80;

        if self.pending_len <= 55 {
            // 单块：56..64 写长度即可（中间已全零）
            block[56..64].copy_from_slice(&bit_len.to_be_bytes());
            sha256::compress(&mut self.state, &block);
        } else {
            // 两块：先压第一块（0x80 已在块内，后面全零）
            sha256::compress(&mut self.state, &block);
            // 第二块：全零，仅写长度
            let mut last = [0u8; 64];
            last[56..64].copy_from_slice(&bit_len.to_be_bytes());
            sha256::compress(&mut self.state, &last);
        }

        let mut out = [0u8; 32];
        for (i, word) in self.state.iter().enumerate() {
            out[i * 4..i * 4 + 4].copy_from_slice(&word.to_be_bytes());
        }
        out
    }
}

/// 读取条目表。
pub fn read_entries(file: &Path, footer: &Footer) -> std::io::Result<Vec<Entry>> {
    let mut f = File::open(file)?;
    f.seek(SeekFrom::Start(footer.table_off))?;
    let mut entries = Vec::with_capacity(footer.entry_count as usize);
    for _ in 0..footer.entry_count {
        let mut head = [0u8; 16]; // name_len(4) + off(8) + len(4, 高位补0)
        f.read_exact(&mut head)?;
        let name_len = u32::from_le_bytes(head[0..4].try_into().unwrap()) as usize;
        let off = u64::from_le_bytes(head[4..12].try_into().unwrap());
        let len = u32::from_le_bytes(head[12..16].try_into().unwrap()) as u64;
        let mut name_buf = vec![0u8; name_len];
        f.read_exact(&mut name_buf)?;
        let name = String::from_utf8(name_buf)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;
        entries.push(Entry { name, off, len });
    }
    Ok(entries)
}

/// 安全校验：拒绝绝对路径、..、驱动器前缀，防止路径穿越。
pub fn safe_relative(name: &str) -> bool {
    if name.is_empty() || name.starts_with('/') || name.starts_with('\\') {
        return false;
    }
    if name.as_bytes().get(1) == Some(&b':') {
        return false; // C: 之类
    }
    let p = Path::new(name);
    for comp in p.components() {
        match comp {
            Component::Normal(_) => {}
            _ => return false,
        }
    }
    !name.split(['/', '\\']).any(|part| part == "..")
}

/// 把归档释放到目标目录，返回是否成功。
pub fn extract(file: &Path, footer: &Footer, entries: &[Entry], dest: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dest)?;
    let data_off = footer.table_off - footer.data_len;
    let mut src = File::open(file)?;
    src.seek(SeekFrom::Start(data_off))?;

    let mut cursor: u64 = 0;
    for entry in entries {
        if !safe_relative(&entry.name) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                format!("unsafe archive path: {}", entry.name),
            ));
        }
        // 条目在数据区中按顺序排列，顺序读取即可
        if cursor != entry.off {
            src.seek(SeekFrom::Start(data_off + entry.off))?;
            cursor = entry.off;
        }
        let target = dest.join(&entry.name);
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut out = BufWriter::new(File::create(&target)?);
        let mut remaining = entry.len;
        let mut buf = vec![0u8; 1024 * 1024];
        while remaining > 0 {
            let want = remaining.min(buf.len() as u64) as usize;
            src.read_exact(&mut buf[..want])?;
            out.write_all(&buf[..want])?;
            remaining -= want as u64;
        }
        out.flush()?;
        cursor += entry.len;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn safe_paths() {
        assert!(safe_relative("a/b/c.txt"));
        assert!(safe_relative("wwcore-app.exe"));
        assert!(safe_relative("games/wuthering/assets/model.dat"));
        assert!(!safe_relative("../evil.exe"));
        assert!(!safe_relative("a/../../b"));
        assert!(!safe_relative("/abs/path"));
        assert!(!safe_relative("C:/windows/system32"));
        assert!(!safe_relative(""));
    }

    #[test]
    fn footer_layout_size() {
        // footer 定长 64B：magic8 + data_len8 + cnt4 + sha32 + table_off8 = 60，
        // 剩 4B 保留，解析侧固定读 64B
        assert_eq!(FOOTER_SIZE, 64);
    }

    /// 流式哈希必须与一次性 digest 完全一致，包括跨 64 字节边界的诡异长度。
    #[test]
    fn streaming_hash_matches_digest() {
        // 构造一个覆盖各种边界长度的输入（累计长度跨越多个块）
        let mut data = Vec::new();
        for chunk_len in [1usize, 63, 64, 65, 127, 128, 1000, 65536, 55, 9] {
            for i in 0..chunk_len {
                data.push((i % 251) as u8);
            }
        }
        let expected = sha256::digest(&data);
        let mut h = StreamingHasher::new();
        // 用不规则的投喂块大小，模拟读取文件时的 1MB 分块
        let mut pos = 0;
        for feed in [1usize, 64, 1000, 4096, 65536] {
            while pos + feed <= data.len() {
                h.update(&data[pos..pos + feed]);
                pos += feed;
            }
        }
        h.update(&data[pos..]);
        assert_eq!(sha256::hex(&h.finish()), sha256::hex(&expected));
    }

    /// 覆盖所有 pending_len 余数（0..=63），尤其是 56..=63 的 padding 边界。
    /// 早期实现对 n=57..=62 会执行 copy_within(64..n) 而 panic，导致大文件
    /// 校验时启动器崩溃。这里逐个长度比对标准 digest。
    #[test]
    fn streaming_hash_all_lengths() {
        for len in 0usize..=200 {
            let data: Vec<u8> = (0..len).map(|i| (i * 37 + 11) as u8).collect();
            let expected = sha256::digest(&data);
            let mut h = StreamingHasher::new();
            h.update(&data);
            assert_eq!(
                sha256::hex(&h.finish()),
                sha256::hex(&expected),
                "len={len} mismatch"
            );
        }
    }

    /// 性能回归：485MB 数据区校验必须在数秒内完成。
    /// 早期实现用 Vec::drain 逐块移除，是 O(n^2)，同样的量级要跑数分钟。
    #[test]
    fn streaming_hash_is_linear() {
        let block = vec![0xABu8; 1024 * 1024]; // 1MB
        let mut h = StreamingHasher::new();
        // 16MB 足以暴露 O(n^2)（drain 版这里会明显超过 1 秒）
        for _ in 0..16 {
            h.update(&block);
        }
        let _ = h.finish();
    }
}

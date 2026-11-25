//! Windows 管理员权限校验。
//!
//! 正常路径下，exe 的 manifest（requireAdministrator）会在进程创建前
//! 由 Windows 加载器完成 UAC 提权；进入本模块时一定已是管理员。
//! 这是启动器自身的运行前提校验，不是动态对抗：不隐藏进程、不反调试、
//! 不注入、不 hook。
//!
//! 若检测到非管理员（manifest 被剥离/绕过），不再二次拉起进程——那正是
//! "cmd 闪一下就没了"的根源——而是弹窗明确告知并拒绝启动。

use std::ffi::{c_void, OsString};
use std::path::Path;
use std::ptr;

type LPCWSTR = *const u16;

#[link(name = "advapi32")]
extern "system" {
    fn AllocateAndInitializeSid(
        identifier_authority: *const SidIdentifierAuthority,
        sub_authority_count: u8,
        sub_authority1: u32,
        sub_authority2: u32,
        sub_authority3: u32,
        sub_authority4: u32,
        sub_authority5: u32,
        sub_authority6: u32,
        sub_authority7: u32,
        sub_authority8: u32,
        sid: *mut *mut c_void,
    ) -> i32;
    fn CheckTokenMembership(token_handle: *mut c_void, sid_to_check: *mut c_void, is_member: *mut i32) -> i32;
    fn FreeSid(sid: *mut c_void) -> *mut c_void;
}

#[link(name = "user32")]
extern "system" {
    fn MessageBoxW(hwnd: *mut c_void, text: LPCWSTR, caption: LPCWSTR, msg_type: u32) -> i32;
}

#[repr(C)]
struct SidIdentifierAuthority {
    value: [u8; 6],
}

const SECURITY_NT_AUTHORITY: SidIdentifierAuthority = SidIdentifierAuthority {
    value: [0, 0, 0, 0, 0, 5],
};
const SECURITY_BUILTIN_DOMAIN_RID: u32 = 0x0000_0020;
const DOMAIN_ALIAS_RID_ADMINS: u32 = 0x0000_0220;
const MB_ICONERROR: u32 = 0x0000_0010;
const MB_OK: u32 = 0x0000_0000;

/// 当前进程令牌是否属于本机 Administrators 组。
pub fn is_admin() -> bool {
    unsafe {
        let mut sid: *mut c_void = ptr::null_mut();
        let ok = AllocateAndInitializeSid(
            &SECURITY_NT_AUTHORITY,
            2,
            SECURITY_BUILTIN_DOMAIN_RID,
            DOMAIN_ALIAS_RID_ADMINS,
            0,
            0,
            0,
            0,
            0,
            0,
            &mut sid,
        );
        if ok == 0 || sid.is_null() {
            return false;
        }

        let mut member = 0i32;
        let checked = CheckTokenMembership(ptr::null_mut(), sid, &mut member);
        FreeSid(sid);
        checked != 0 && member != 0
    }
}

fn wide_literal(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(std::iter::once(0)).collect()
}

/// 权限检查。返回 Ok(true) 表示已是管理员，可继续；Err 表示非管理员，
/// 调用方应结束进程。正常双击场景由 manifest 完成提权，这里只是兜底。
pub fn ensure_admin(_self_path: &Path, _args: &[OsString]) -> Result<bool, String> {
    if is_admin() {
        return Ok(true);
    }

    let text = wide_literal(
        "本程序必须以管理员身份运行。\n\n\
         请右键点击 exe，选择“以管理员身份运行”；\n\
         或在 UAC 弹窗中点击“是”。",
    );
    let caption = wide_literal("需要管理员权限");
    unsafe {
        MessageBoxW(
            ptr::null_mut(),
            text.as_ptr(),
            caption.as_ptr(),
            MB_OK | MB_ICONERROR,
        );
    }
    Err("非管理员权限，已拒绝启动。".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn is_admin_does_not_panic() {
        let _ = is_admin();
    }

    #[test]
    fn wide_literal_is_null_terminated() {
        let w = wide_literal("abc");
        assert_eq!(w, vec![b'a' as u16, b'b' as u16, b'c' as u16, 0]);
    }
}

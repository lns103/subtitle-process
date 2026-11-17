//! 引擎 supervisor：进程生命周期 + JSONL 协议路由。
//!
//! 业务逻辑一律不放在 Rust；这里只负责 spawn、读写、请求匹配、事件转发。

pub mod commands;
pub mod protocol;
pub mod supervisor;

pub use supervisor::Supervisor;

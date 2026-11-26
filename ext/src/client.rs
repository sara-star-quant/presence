use std::env;
use std::fs;
use std::io::{self, Read, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};
use std::thread;

// How long to wait for the daemon's answer. The host kills a hook at 5 to 10 seconds (hooks/hooks.json), so waiting
// less than that only turns a slow hook into a silently dropped one, a Stop block included.
const READ_TIMEOUT_MS: u64 = 8000;

fn get_state_dir() -> PathBuf {
    if let Ok(val) = env::var("PRESENCE_STATE") {
        PathBuf::from(val)
    } else {
        let mut path = PathBuf::from(env::var("HOME").unwrap_or_else(|_| "/tmp".into()));
        path.push(".claude");
        path.push("presence");
        path
    }
}

fn resolve_python(state_dir: &Path) -> String {
    let pinned = state_dir.join(".python_bin");
    if let Ok(content) = fs::read_to_string(&pinned) {
        let bin = content.trim();
        if !bin.is_empty() && Path::new(bin).exists() {
            return bin.to_string();
        }
    }
    // Fallback search
    if Command::new("python3.14t").arg("--version").output().is_ok() {
        "python3.14t".to_string()
    } else {
        "python3".to_string()
    }
}

fn get_plugin_root() -> PathBuf {
    if let Ok(val) = env::var("CLAUDE_PLUGIN_ROOT") {
        return PathBuf::from(val);
    }
    // If the executable is lib/presence-client or a symlink to it
    if let Ok(exe) = env::current_exe() {
        if let Ok(resolved) = fs::canonicalize(&exe) {
            if let Some(lib_dir) = resolved.parent() {
                if let Some(root) = lib_dir.parent() {
                    return root.to_path_buf();
                }
            }
        }
    }
    PathBuf::from(".")
}

// Run the hook in a fresh interpreter, the same path the bash wrapper takes. Used when the daemon cannot boot or died
// mid-request, so a gate decision still happens.
fn run_direct(python_bin: &str, plugin_root: &Path, hook_name: &str, stdin_data: &str) {
    let cli_py = plugin_root.join("lib").join("cli.py");
    let mut child = Command::new(python_bin)
        .arg(cli_py)
        .arg("hook")
        .arg(hook_name)
        .env("CLAUDE_PLUGIN_ROOT", plugin_root.to_string_lossy().to_string())
        .stdin(Stdio::piped())
        .spawn()
        .expect("failed to spawn fallback python");
    if let Some(mut stdin) = child.stdin.take() {
        let _ = stdin.write_all(stdin_data.as_bytes());
    }
    let _ = child.wait();
}

fn main() {
    let args: Vec<String> = env::args().collect();

    // --version: emit the compiled ext crate version (env!CARGO_PKG_VERSION
    // at compile time from ext/Cargo.toml) and exit. Useful for bug reports
    // and for install.sh --verify post-build sanity. Must be the first arg
    // gate so it short-circuits before any of the daemon / hook plumbing.
    if args.len() == 2 && args[1] == "--version" {
        println!("presence-client {}", env!("CARGO_PKG_VERSION"));
        return;
    }

    // Hook name: prefer argv[1] (passed by _common.sh exec_hook),
    // fall back to exe basename for direct invocation.
    let hook_name = if args.len() > 1 {
        // Strip .py suffix: "hook_session_start.py" -> "session-start"
        let raw = &args[1];
        raw.strip_prefix("hook_").unwrap_or(raw)
            .strip_suffix(".py").unwrap_or(raw)
            .replace('_', "-")
    } else {
        let exe_name = Path::new(&args[0])
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string();
        exe_name.strip_suffix(".sh").unwrap_or(&exe_name).to_string()
    };

    let mut stdin_data = String::new();
    // read stdin if available (non-blocking or just read to string)
    // Actually, Claude code pipes JSON to stdin.
    let _ = io::stdin().read_to_string(&mut stdin_data);

    let state_dir = get_state_dir();
    let sock_path = state_dir.join("presence.sock");

    let payload = format!(
        "{{\"hook\": \"{}\", \"stdin\": {}}}\n",
        hook_name,
        serde_json::to_string(&stdin_data).unwrap_or_else(|_| "\"\"".to_string())
    );

    // Try connect
    let mut stream = match UnixStream::connect(&sock_path) {
        Ok(s) => s,
        Err(_) => {
            // No daemon is answering. The daemon owns its socket and pid files and takes a lock at start, so a
            // second one exits at once and a stale socket is replaced by whichever process holds the lock. This
            // client never kills by pid file (a stale pid can name an unrelated process) and never deletes
            // another process's files.
            let plugin_root = get_plugin_root();
            let daemon_py = plugin_root.join("lib").join("daemon.py");
            let python_bin = resolve_python(&state_dir);

            // Spawn daemon
            let lib_dir = plugin_root.join("lib");
            let _ = Command::new(&python_bin)
                .arg(daemon_py)
                .env("CLAUDE_PLUGIN_ROOT", plugin_root.to_string_lossy().to_string())
                .env("PYTHONPATH", lib_dir.to_string_lossy().to_string())
                .env("PYTHONNOUSERSITE", "1")
                .env("PYTHON_JIT", "1")
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn();

            // Wait for socket
            let start = Instant::now();
            let mut connected_stream = None;
            while start.elapsed() < Duration::from_millis(2000) {
                if let Ok(s) = UnixStream::connect(&sock_path) {
                    connected_stream = Some(s);
                    break;
                }
                thread::sleep(Duration::from_millis(10));
            }

            match connected_stream {
                Some(s) => s,
                None => {
                    // The daemon did not come up: run the hook directly so the decision is not lost.
                    run_direct(&python_bin, &plugin_root, &hook_name, &stdin_data);
                    return;
                }
            }
        }
    };

    stream.set_read_timeout(Some(Duration::from_millis(READ_TIMEOUT_MS))).ok();
    let sent = stream.write_all(payload.as_bytes()).is_ok();
    let _ = stream.shutdown(Shutdown::Write); // signal EOF to daemon
    let mut response = String::new();
    let read = if sent { stream.read_to_string(&mut response) } else { Err(io::Error::from(io::ErrorKind::BrokenPipe)) };
    match read {
        Ok(_) => print!("{}", response),
        Err(e) if e.kind() == io::ErrorKind::WouldBlock || e.kind() == io::ErrorKind::TimedOut => {
            // The daemon may still be running the hook, so do not run it a second time. Say so where a log reads it.
            eprintln!("presence: the daemon did not answer within {} ms; this hook's output was dropped", READ_TIMEOUT_MS);
        }
        Err(_) => {
            // The daemon died or reset the connection before answering: run the hook directly.
            let plugin_root = get_plugin_root();
            let python_bin = resolve_python(&state_dir);
            run_direct(&python_bin, &plugin_root, &hook_name, &stdin_data);
        }
    }
}

//! Desktop shell: one window, plus the local HTTP backend (`src/admin_server.py`)
//! started on a random port with a random token. Closing the window hides it;
//! quitting stops the backend. Watch tasks run in their own session and outlive both.

use std::fs;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, RunEvent, WindowEvent};

#[derive(Clone, Serialize, Deserialize)]
struct BackendConfig {
    root: String,
    python: String,
}

#[derive(Clone, Serialize)]
struct BackendInfo {
    url: String,
    token: String,
}

#[derive(Default)]
struct Backend {
    child: Option<Child>,
    info: Option<BackendInfo>,
}

struct Shared(Mutex<Backend>);

/// Write end of the lifecycle watchdog's stdin pipe, held for the whole process.
///
/// The watchdog (`src/push.py app-watch`) blocks reading stdin; the kernel closes
/// this pipe when the app dies for any reason, which is its signal to send the
/// "app exited" push. Dropping the handle would close it early.
#[derive(Default)]
struct Lifecycle(Mutex<Option<ChildStdin>>);

fn default_config() -> BackendConfig {
    // desktop/src-tauri → the project root.
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    BackendConfig {
        root: root.canonicalize().unwrap_or(root).display().to_string(),
        python: "/usr/bin/python3".into(),
    }
}

fn config_path(app: &AppHandle) -> Option<PathBuf> {
    app.path().app_config_dir().ok().map(|dir| dir.join("backend.json"))
}

fn load_config(app: &AppHandle) -> BackendConfig {
    config_path(app)
        .and_then(|path| fs::read_to_string(path).ok())
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_else(default_config)
}

fn save_config(app: &AppHandle, config: &BackendConfig) -> Result<(), String> {
    let path = config_path(app).ok_or("无法确定配置目录。")?;
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    fs::write(path, serde_json::to_string_pretty(config).unwrap()).map_err(|e| e.to_string())
}

fn random_token() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    fs::File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut bytes))
        .map_err(|e| e.to_string())?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

fn spawn(config: &BackendConfig) -> Result<(Child, BackendInfo, u16), String> {
    let root = PathBuf::from(&config.root);
    if !root.join("src/admin_server.py").exists() {
        return Err(format!("项目目录「{}」下没有 src/admin_server.py。", config.root));
    }
    let server_python = root.join(".venv/bin/python");
    if !server_python.exists() {
        return Err("项目目录下没有 .venv。先在项目目录运行：/usr/bin/python3 -m venv .venv && \
                    .venv/bin/pip install -r requirements-server.txt"
            .into());
    }
    let port = TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map_err(|e| e.to_string())?
        .port();
    let token = random_token()?;
    fs::create_dir_all(root.join("var")).map_err(|e| e.to_string())?;
    let log = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(root.join("var/admin-server.log"))
        .map_err(|e| e.to_string())?;
    let child = Command::new(server_python)
        .args(["-B", "src/admin_server.py", "--port", &port.to_string(), "--exit-with-parent"])
        .current_dir(&root)
        .env("CMB_ADMIN_TOKEN", &token)
        .env("CMB_PYTHON", &config.python)
        .stdin(Stdio::null())
        .stdout(log.try_clone().map_err(|e| e.to_string())?)
        .stderr(log)
        .spawn()
        .map_err(|e| format!("无法启动后端：{e}"))?;
    let info = BackendInfo { url: format!("http://127.0.0.1:{port}"), token };
    Ok((child, info, port))
}

/// Starts the backend if needed and waits until it accepts connections.
fn ensure_started(app: &AppHandle) -> Result<BackendInfo, String> {
    let shared = app.state::<Shared>();
    let mut backend = shared.0.lock().unwrap();
    let running = backend.child.as_mut().is_some_and(|child| matches!(child.try_wait(), Ok(None)));
    if let (true, Some(info)) = (running, backend.info.as_ref()) {
        return Ok(info.clone());
    }
    let (mut child, info, port) = spawn(&load_config(app))?;
    let deadline = Instant::now() + Duration::from_secs(10);
    while TcpStream::connect(("127.0.0.1", port)).is_err() {
        if !matches!(child.try_wait(), Ok(None)) {
            return Err("后端启动后立即退出，详见项目的 var/admin-server.log。".into());
        }
        if Instant::now() > deadline {
            let _ = child.kill();
            return Err("后端启动超时，详见项目的 var/admin-server.log。".into());
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    backend.child = Some(child);
    backend.info = Some(info.clone());
    Ok(info)
}

fn stop(app: &AppHandle) {
    let shared = app.state::<Shared>();
    let mut backend = shared.0.lock().unwrap();
    if let Some(mut child) = backend.child.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    backend.info = None;
}

#[tauri::command]
async fn backend(app: AppHandle) -> Result<BackendInfo, String> {
    tauri::async_runtime::spawn_blocking(move || ensure_started(&app))
        .await
        .map_err(|e| e.to_string())?
}

#[tauri::command]
fn backend_config(app: AppHandle) -> BackendConfig {
    load_config(&app)
}

#[tauri::command]
async fn set_backend_config(app: AppHandle, config: BackendConfig) -> Result<BackendConfig, String> {
    save_config(&app, &config)?;
    tauri::async_runtime::spawn_blocking(move || {
        stop(&app);
        ensure_started(&app).map(|_| load_config(&app))
    })
    .await
    .map_err(|e| e.to_string())?
}

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn timestamp() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs().to_string())
        .unwrap_or_else(|_| "?".into())
}

fn append_push_log(root: &Path, line: &str) {
    let _ = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(root.join("var/push.log"))
        .and_then(|mut log| log.write_all(format!("{line}\n").as_bytes()));
}

/// Starts `src/push.py app-watch`, the watchdog that pushes "管理 App 已启动" and
/// (after this process ends) "管理 App 已退出".
///
/// Why a pipe and a separate process instead of sending the exit push from
/// `RunEvent::Exit`: Tauri's exit handlers are not guaranteed to run when the app is
/// killed (`pkill`, crash, SIGKILL), but the kernel always closes this pipe write end
/// when the process dies — the watchdog then reads EOF and sends the push by itself.
/// Keeping the send in another process also means Cmd-Q never waits for the network.
fn start_lifecycle_watch(app: &AppHandle) {
    let config = load_config(app);
    let root = PathBuf::from(&config.root);
    let _ = fs::create_dir_all(root.join("var"));
    // Watchdog diagnostics go next to the backend log; if the log cannot be opened,
    // stay quiet rather than letting stderr break spawn().
    let stderr = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(root.join("var/push.log"))
        .map(Stdio::from)
        .unwrap_or_else(|_| Stdio::null());
    match Command::new(&config.python)
        .args(["-B", "src/push.py", "app-watch"])
        .current_dir(&root)
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(stderr)
        .spawn()
    {
        Ok(mut child) => {
            // Keeping the write end in managed state is what holds the pipe open:
            // the watchdog must not see EOF (and send the exit push) while the app runs.
            *app.state::<Lifecycle>().0.lock().unwrap() = child.stdin.take();
            // Reap the child in the background so it never becomes a zombie. The
            // watchdog normally ends only after this process closes the pipe.
            std::thread::spawn(move || {
                let _ = child.wait();
            });
        }
        Err(error) => append_push_log(
            &root,
            &format!("{} 无法启动管理 App 生命周期推送进程：{error}", timestamp()),
        ),
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| show_main(app)))
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_notification::init())
        .manage(Shared(Mutex::new(Backend::default())))
        .manage(Lifecycle::default())
        // Single-instance makes every second launch exit before `run()`/setup, so the
        // watchdog (and its start push) is only ever started by the one real instance.
        .setup(|app| {
            start_lifecycle_watch(app.handle());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend, backend_config, set_backend_config])
        .on_window_event(|window, event| {
            // The close button and Cmd-W only hide the window; Cmd-Q quits.
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building the app")
        .run(|app, event| match event {
            #[cfg(target_os = "macos")]
            RunEvent::Reopen { .. } => show_main(app),
            RunEvent::Exit => stop(app),
            _ => {}
        });
}

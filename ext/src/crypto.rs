use pyo3::prelude::*;

#[cfg(target_os = "macos")]
mod platform {
    use security_framework::passwords::{get_generic_password, set_generic_password, delete_generic_password};

    const SERVICE: &str = "presence";
    const ACCOUNT: &str = "presence-data-key";

    pub fn get_key() -> Option<Vec<u8>> {
        get_generic_password(SERVICE, ACCOUNT)
            .ok()
            .map(|pwd| hex::decode(String::from_utf8_lossy(&pwd).trim()).ok())
            .flatten()
    }

    pub fn set_key(key: &[u8]) -> bool {
        let _ = delete_generic_password(SERVICE, ACCOUNT);
        let hex_key = hex::encode(key);
        set_generic_password(SERVICE, ACCOUNT, hex_key.as_bytes()).is_ok()
    }

    pub fn delete_key() -> bool {
        delete_generic_password(SERVICE, ACCOUNT).is_ok()
    }
}

#[cfg(target_os = "linux")]
mod platform {
    use secret_service::{EncryptionType, SecretService};
    use std::collections::HashMap;

    const SERVICE: &str = "presence";
    const ACCOUNT: &str = "presence-data-key";

    pub fn get_key() -> Option<Vec<u8>> {
        let ss = SecretService::connect(EncryptionType::Plain).ok()?;
        let collection = ss.get_default_collection().ok()?;
        let mut props = HashMap::new();
        props.insert("service", SERVICE);
        props.insert("account", ACCOUNT);
        let items = collection.search_items(props).ok()?;
        if let Some(item) = items.first() {
            let secret = item.get_secret().ok()?;
            let hex_str = std::str::from_utf8(secret.as_slice()).ok()?.trim();
            hex::decode(hex_str).ok()
        } else {
            None
        }
    }

    pub fn set_key(key: &[u8]) -> bool {
        if let Ok(ss) = SecretService::connect(EncryptionType::Plain) {
            if let Ok(collection) = ss.get_default_collection() {
                let mut props = HashMap::new();
                props.insert("service", SERVICE);
                props.insert("account", ACCOUNT);
                let hex_key = hex::encode(key);
                return collection.create_item(
                    "presence data key",
                    props,
                    hex_key.as_bytes(),
                    true,
                    "text/plain"
                ).is_ok();
            }
        }
        false
    }

    pub fn delete_key() -> bool {
        if let Ok(ss) = SecretService::connect(EncryptionType::Plain) {
            if let Ok(collection) = ss.get_default_collection() {
                let mut props = HashMap::new();
                props.insert("service", SERVICE);
                props.insert("account", ACCOUNT);
                if let Ok(items) = collection.search_items(props) {
                    for item in items {
                        let _ = item.delete();
                    }
                    return true;
                }
            }
        }
        false
    }
}

#[cfg(not(any(target_os = "macos", target_os = "linux")))]
mod platform {
    pub fn get_key() -> Option<Vec<u8>> { None }
    pub fn set_key(_: &[u8]) -> bool { false }
    pub fn delete_key() -> bool { false }
}

#[pyfunction]
fn get_key(_py: Python) -> Option<Vec<u8>> {
    platform::get_key()
}

#[pyfunction]
fn set_key(_py: Python, key: &[u8]) -> bool {
    platform::set_key(key)
}

#[pyfunction]
fn delete_key(_py: Python) -> bool {
    platform::delete_key()
}

pub fn register(m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(get_key, m)?)?;
    m.add_function(wrap_pyfunction!(set_key, m)?)?;
    m.add_function(wrap_pyfunction!(delete_key, m)?)?;
    Ok(())
}

// pyo3 0.22+ Bound API: #[pymodule] expects &Bound<'_, PyModule>; the GIL token
// is reachable via m.py(). Submodules are constructed with PyModule::new which
// returns Bound<PyModule> directly. See migration notes in CHANGELOG v0.5.3.
#[cfg(feature = "pyext")]
use pyo3::prelude::*;

#[cfg(feature = "pyext")]
mod crypto;
#[cfg(feature = "pyext")]
mod git;

#[cfg(feature = "pyext")]
#[pymodule]
fn presence_ext(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Expose the compiled ext crate version so the Python plugin can
    // cross-check it against lib/__init__.py._MIN_EXT_VERSION at SessionStart.
    // env!("CARGO_PKG_VERSION") evaluates at compile time from ext/Cargo.toml.
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;

    let crypto_mod = PyModule::new(m.py(), "crypto")?;
    crypto::register(&crypto_mod)?;
    m.add_submodule(&crypto_mod)?;

    let git_mod = PyModule::new(m.py(), "git")?;
    git::register(&git_mod)?;
    m.add_submodule(&git_mod)?;

    Ok(())
}

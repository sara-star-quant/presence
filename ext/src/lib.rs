#[cfg(feature = "pyext")]
use pyo3::prelude::*;

#[cfg(feature = "pyext")]
mod crypto;
#[cfg(feature = "pyext")]
mod git;

#[cfg(feature = "pyext")]
#[pymodule]
fn presence_ext(_py: Python, m: &PyModule) -> PyResult<()> {
    let crypto_mod = PyModule::new(_py, "crypto")?;
    crypto::register(crypto_mod)?;
    m.add_submodule(crypto_mod)?;

    let git_mod = PyModule::new(_py, "git")?;
    git::register(git_mod)?;
    m.add_submodule(git_mod)?;

    Ok(())
}

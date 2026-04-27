use pyo3::prelude::*;
use git2::{Repository, Sort};
use pyo3::types::PyDict;

#[pyfunction]
fn get_head_commit(py: Python, cwd: &str) -> PyResult<Option<PyObject>> {
    if let Ok(repo) = Repository::open(cwd) {
        if let Ok(head) = repo.head() {
            if let Ok(commit) = head.peel_to_commit() {
                let dict = PyDict::new(py);
                dict.set_item("sha", commit.id().to_string())?;
                dict.set_item("ct", commit.time().seconds())?;
                dict.set_item("message", commit.message().unwrap_or("").trim())?;
                return Ok(Some(dict.into()));
            }
        }
    }
    Ok(None)
}

#[pyfunction]
fn scan_for_revert(py: Python, cwd: &str, since_ts: i64, tracked_shas: Vec<String>) -> PyResult<Vec<PyObject>> {
    let mut findings = Vec::new();
    if let Ok(repo) = Repository::open(cwd) {
        if let Ok(mut revwalk) = repo.revwalk() {
            revwalk.push_head().unwrap_or(());
            revwalk.set_sorting(Sort::TIME).unwrap_or(());

            for oid in revwalk.flatten() {
                if let Ok(commit) = repo.find_commit(oid) {
                    if commit.time().seconds() < since_ts {
                        break;
                    }
                    let msg = commit.message().unwrap_or("").to_lowercase();
                    if msg.starts_with("revert ") {
                        for tracked in &tracked_shas {
                            let short_tracked = if tracked.len() >= 7 { &tracked[..7] } else { tracked };
                            if msg.contains(short_tracked) || msg.contains(tracked) {
                                let dict = PyDict::new(py);
                                dict.set_item("kind", "revert")?;
                                dict.set_item("tracked", tracked)?;
                                dict.set_item("by", commit.id().to_string())?;
                                dict.set_item("ts", commit.time().seconds())?;
                                dict.set_item("message", commit.message().unwrap_or("").trim())?;
                                findings.push(dict.into());
                                break;
                            }
                        }
                    }
                }
            }
        }
    }
    Ok(findings)
}

pub fn register(m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(get_head_commit, m)?)?;
    m.add_function(wrap_pyfunction!(scan_for_revert, m)?)?;
    Ok(())
}

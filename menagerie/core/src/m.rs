//! Transcendental functions via `libm`, never the platform's, so the browser
//! build and the native build compute bit-identical trajectories.

pub fn sin(x: f32) -> f32 {
    libm::sinf(x)
}
pub fn cos(x: f32) -> f32 {
    libm::cosf(x)
}
pub fn tanh(x: f32) -> f32 {
    libm::tanhf(x)
}
pub fn atan2(y: f32, x: f32) -> f32 {
    libm::atan2f(y, x)
}
pub fn cbrt(x: f32) -> f32 {
    libm::cbrtf(x)
}
pub fn ln(x: f32) -> f32 {
    libm::logf(x)
}

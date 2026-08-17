// CloudFront Function (cloudfront-js-2.0)
// 关联到 default cache behavior 的 viewer-response 事件
// 作用：剥离被缓存匿名页面的 Set-Cookie，防止 session 串号
function handler(event) {
    var response = event.response;
    // 关键：cloudfront-js-2.0 里多值 Set-Cookie 在 response.cookies，不在 headers
    if (response.cookies) {
        response.cookies = {};
    }
    if (response.headers && response.headers['set-cookie']) {
        delete response.headers['set-cookie'];
    }
    return response;
}

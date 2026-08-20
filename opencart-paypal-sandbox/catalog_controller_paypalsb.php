<?php
namespace Opencart\Catalog\Controller\Extension\Opencart\Payment;
class PaypalSb extends \Opencart\System\Engine\Controller {
	public function index(): string {
		$this->load->language('extension/opencart/payment/paypalsb');
		return $this->load->view('extension/opencart/payment/paypalsb', []);
	}

	private function token(): string {
		$cid = $this->config->get('payment_paypalsb_client_id');
		$sec = $this->config->get('payment_paypalsb_secret');
		$ch = curl_init('https://api-m.sandbox.paypal.com/v1/oauth2/token');
		curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER=>true, CURLOPT_POST=>true,
			CURLOPT_USERPWD=>$cid.':'.$sec,
			CURLOPT_POSTFIELDS=>'grant_type=client_credentials',
			CURLOPT_HTTPHEADER=>['Accept: application/json']]);
		$r = json_decode(curl_exec($ch), true);
		return $r['access_token'] ?? '';
	}

	public function confirm(): void {
		$this->load->language('extension/opencart/payment/paypalsb');
		$json = [];
		if (!isset($this->session->data['order_id'])) { $json['error'] = $this->language->get('error_order'); }
		if (!$json) {
			$this->load->model('checkout/order');
			$order = $this->model_checkout_order->getOrder($this->session->data['order_id']);
			$token = $this->token();
			if (!$token) { $json['error'] = 'PayPal auth failed'; }
			else {
				$total = number_format($order['total'] * $order['currency_value'], 2, '.', '');
				$cur = $order['currency_code'];
				$rtn = $this->url->link('extension/opencart/payment/paypalsb.callback', 'language=' . $this->config->get('config_language'), true);
				$cancel = $this->url->link('checkout/checkout', 'language=' . $this->config->get('config_language'), true);
				$body = json_encode(['intent'=>'CAPTURE',
					'purchase_units'=>[['amount'=>['currency_code'=>$cur,'value'=>$total],
						'custom_id'=>(string)$order['order_id']]],
					'payment_source'=>['paypal'=>['experience_context'=>[
						'return_url'=>$rtn, 'cancel_url'=>$cancel,
						'user_action'=>'PAY_NOW']]]]);
				$ch = curl_init('https://api-m.sandbox.paypal.com/v2/checkout/orders');
				curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER=>true, CURLOPT_POST=>true,
					CURLOPT_POSTFIELDS=>$body,
					CURLOPT_HTTPHEADER=>['Content-Type: application/json','Authorization: Bearer '.$token]]);
				$r = json_decode(curl_exec($ch), true);
				$approve = '';
				foreach (($r['links'] ?? []) as $l) { if ($l['rel']=='payer-action'||$l['rel']=='approve') $approve = $l['href']; }
				if ($approve) {
					$this->session->data['paypalsb_order'] = $r['id'];
					$json['redirect'] = $approve;
				} else { $json['error'] = 'PayPal create order failed: '.json_encode($r); }
			}
		}
		$this->response->addHeader('Content-Type: application/json');
		$this->response->setOutput(json_encode($json));
	}

	public function callback(): void {
		$this->load->language('extension/opencart/payment/paypalsb');
		$this->load->model('checkout/order');
		$ppid = $this->session->data['paypalsb_order'] ?? ($this->request->get['token'] ?? '');
		$token = $this->token();
		$ok = false;
		if ($ppid && $token) {
			$ch = curl_init('https://api-m.sandbox.paypal.com/v2/checkout/orders/'.$ppid.'/capture');
			curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER=>true, CURLOPT_POST=>true,
				CURLOPT_POSTFIELDS=>'{}',
				CURLOPT_HTTPHEADER=>['Content-Type: application/json','Authorization: Bearer '.$token]]);
			$r = json_decode(curl_exec($ch), true);
			if (($r['status'] ?? '') == 'COMPLETED') $ok = true;
		}
		if ($ok && isset($this->session->data['order_id'])) {
			$this->model_checkout_order->addHistory($this->session->data['order_id'], $this->config->get('payment_paypalsb_order_status_id') ?: 2);
			unset($this->session->data['paypalsb_order']);
			$this->response->redirect($this->url->link('checkout/success', 'language=' . $this->config->get('config_language'), true));
		} else {
			$this->response->redirect($this->url->link('checkout/failure', 'language=' . $this->config->get('config_language'), true));
		}
	}
}

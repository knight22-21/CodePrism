/**
 * Payment service module.
 */
import { computeHash, formatAmount } from './utils.js';

class PaymentService extends BaseService {
  constructor(config) {
    super(config);
    this.retries = 3;
  }

  async processPayment(amount) {
    if (amount <= 0) return false;
    const hash = computeHash(amount.toString());
    return this._submit(amount, hash);
  }

  _submit(amount, hash) {
    return true;
  }
}

function createService(config) {
  return new PaymentService(config);
}

const DEFAULT_TIMEOUT = 5000;

export { PaymentService, createService, DEFAULT_TIMEOUT };

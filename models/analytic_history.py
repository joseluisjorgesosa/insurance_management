# -*- coding: utf-8 -*-

from openerp import models, fields, api, _
from openerp.exceptions import Warning,ValidationError
from datetime import datetime as dt
from openerp.addons.decimal_precision import decimal_precision as dp
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT
import logging
logger = logging.getLogger(__name__)


class AnalyticHistory(models.Model):
    _name = 'analytic.history'
    _description = 'History of the policy'

    analytic_id = fields.Many2one(
        comodel_name='account.analytic.account', string='Subscription')
    name = fields.Char(string='History number')
    starting_date = fields.Date(
        string='Starting date', default=fields.Date.context_today,
        required=True)
    ending_date = fields.Date(
        string='Ending date', default=fields.Date.context_today, required=True)
    creating_date = fields.Date(
        string='Creating date', default=fields.Date.context_today,
        required=True)
    is_last_situation = fields.Boolean(
        string='Is the last situation', default=False)
    is_validated = fields.Boolean(string='Is validated', default=False)
    capital = fields.Float(
        string='Capital', digit_compute=dp.get_precision('account'))
    eml = fields.Float(
        string='Expected maximum loss',
        digit_compute=dp.get_precision('account'))
    stage_id = fields.Many2one(
        comodel_name='analytic.history.stage', string='Emission type',
        default=lambda self: self.env.ref('insurance_management.devis').id)
    risk_line_ids = fields.One2many(
        comodel_name='analytic_history.risk.line',
        inverse_name='history_id', string='Risks Type')
    parent_id = fields.Many2one(
        comodel_name='analytic.history', string='Parent',
        help='Inherited Amendment')
    invoice_id = fields.Many2one(
        comodel_name='account.invoice', string='Invoice', readonly=True)
    comment = fields.Text(string='Comment', help='Some of your note')
    # apporteur_id = fields.Many2one(
    #    comodel_name='res.apporteur', string='Broker',
    #    help='Initial broker of the contract')

    @api.multi
    def confirm_quotation(self):
        """Confirm Quotation and move state to valid new contract"""
        self.stage_id = self.env.ref('insurance_management.affaire_nouvelle').id

    # TODO
    @api.multi
    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        default.update(name=_("%s (copy)") % (self.name or ''))
        res = super(AroAmendmentLine, self).copy(default)
        new_risk_line = False
        for risk_line_id in self.risk_line_ids:
            if not new_risk_line:
                new_risk_line = risk_line_id.copy()
                new_risk_line.write({'history_id': res.id})
            else:
                new_risk_line_buf = risk_line_id.copy()
                new_risk_line_buf.write({'history_id': res.id})
                new_risk_line += new_risk_line_buf
        return res

    @api.multi
    def _get_all_value(self):
        self.ensure_one()
        res = {}
        list_fields = ['name', 'type_risk_id', 'risk_warranty_tmpl_id']
        om_fields = {
            'warranty_line_ids': ['name', 'warranty_id', 'risk_id'],
            'risk_description_ids': ['name', 'code', 'value']
        }
        new_risk_line = []
        # TODO
        # content of if should be implemented
        if not self._context.get('default', False):
            res['name'] = _('%s (copy)') % self.name or ''
            res['capital'] = self.capital
            res['eml'] = self.eml
            for risk_line_id in self.risk_line_ids:
                new_risk_line.append(risk_line_id.read(list_fields))
        else:
            res['default_name'] = _('%s (copy)') % self.name or ''
            res['default_capital'] = self.capital
            res['default_eml'] = self.eml
            for risk_line_id in self.risk_line_ids:
                l = risk_line_id.read(list_fields)[0]
                # get standard fields
                l['type_risk_id'] = l.get('type_risk_id', False)[0]
                l['risk_warranty_tmpl_id'] = l.get('risk_warranty_tmpl_id', False)
                l['risk_warranty_tmpl_id'] = l.get('risk_warranty_tmpl_id')[0] if l.get('risk_warranty_tmpl_id', False) else False
                del l['id']
                # get o2m fields value
                om_warrantys = risk_line_id.warranty_line_ids.read(om_fields.get('warranty_line_ids'))
                warranty_list = []
                for om_warranty in om_warrantys:
                    del om_warranty['id']
                    om_warranty['warranty_id'] = om_warranty.get('warranty_id')[0] if om_warranty.get('warranty_id') else False
                    om_warranty['risk_id'] = om_warranty.get('risk_id')[0] if om_warranty.get('risk_id') else False
                    warranty_list.append((0, 0, om_warranty))
                l['warranty_line_ids'] = warranty_list
                # =====================================
                om_descs = risk_line_id.risk_description_ids.read(om_fields.get('risk_description_ids'))
                description_list = []
                for om_desc in om_descs:
                    del om_desc['id']
                    description_list.append((0, 0, om_desc))
                l['risk_description_ids'] = description_list
                # =====================================
                l = (0, 0, l)
                new_risk_line.append(l)
            res['default_risk_line_ids'] = new_risk_line
        return res

    @api.model
    def create(self, vals):
        if self._context.get('version_type') in ['renew', 'amendment']:
            parent_amendment_line = self._context.get('parent_amendment_line')
            parent_amendment_line = self.browse(parent_amendment_line)
            parent_amendment_line.write({'is_last_situation': False})
        res = super(AroAmendmentLine, self).create(vals)
        return res

    @api.multi
    def _get_user_journal(self):
        """
        insurance_type: ['V', 'N']
        """
        user_obj = self.env['res.users']
        journal_obj = self.env['account.journal']
        insurance_type = self._context.get('insurance_type')
        user = self._uid
        user_id = user_obj.browse(user)
        # logger.info('\n === user_id = %s' % user_id)
        agency_id = user_id.agency_id
        domain = [('type', '=', 'sale'), ('agency_id', '=', agency_id.id)]
        if insurance_type == 'N':
            journal_code = 'PN%s' % agency_id.code
            domain.append(('code', '=', journal_code))
        logger.info('\n === domain = %s' % domain)
        journal_id = journal_obj.search(domain)
        return journal_id

    @api.constrains('starting_date', 'ending_date')
    def _check_startend_date(self):
        if self.starting_date >= self.ending_date:
            raise ValidationError(_('the effective date must be after the end date'))

    @api.constrains('capital', 'eml')
    def _check_capital(self):
        if self.eml > self.capital:
            raise ValidationError(_('The expected maximum loss should be less than the capital'))

    # TODO
    @api.multi
    def generate_invoice(self):
        """ Generate an invoice in draft state """
        self.ensure_one()
        invline_obj = self.env['account.invoice.line']
        product_obj = self.env['product.product']
        res = {}
        warranty_ids = False
        if self.invoice_id:
            res = {
                'type': 'ir.actions.act_window',
                'name': _('Invoice'),
                'res_model': 'account.invoice',
                'view_type': 'form',
                'view_mode': 'form',
                'view_id': [self.env.ref('account.invoice_form').id],
                'res_id': self.invoice_id.id,
                'target': 'current',
                # 'flags': {'form': {'action_buttons': True, 'options': {'mode': 'edit'}}},
            }
        else:
            for risk_line_id in self.risk_line_ids:
                if not warranty_ids:
                    warranty_ids = risk_line_id.warranty_line_ids.mapped('warranty_id')
                else:
                    warranty_ids += risk_line_id.warranty_line_ids.mapped('warranty_id')
            invoice_line = []
            for warranty_id in warranty_ids:
                compute_line = invline_obj.product_id_change(warranty_id.id, warranty_id.uom_id.id, partner_id=self.analytic_id.subscriber_id.id)
                line = compute_line.get('value', {})
                line.update(product_id=warranty_id.id)
                line.update(quantity=1)
                invoice_line.append((0, 0, line))
            # Insert Accessories in invoice_line
            if self._context.get('insurance_categ') == 'T':
                access_tmpl_id = self.env.ref('aro_custom_v8.product_template_accessoire_terrestre_r0')
                access_id = product_obj.search([('product_tmpl_id', '=', access_tmpl_id.id)])
                accessory_line = invline_obj.product_id_change(access_id.id, access_id.uom_id.id, partner_id=self.analytic_id.subscriber_id.id)
                accessory_line = accessory_line.get('value', {})
                compl_line = {
                    'product_id': access_id.id,
                    'quantity': 1,
                }
                accessory_line.update(compl_line)
                invoice_line.append((0, 0, accessory_line))
            # =========================================================
            elif self._context.get('insurance_categ') == 'M':
                access_tmpl_id = self.env.ref('aro_custom_v8.product_template_accessoire_maritime_r0')
                access_id = product_obj.search([('product_tmpl_id', '=', access_tmpl_id.id)])
                accessory_line = invline_obj.product_id_change(access_id.id, access_id.uom_id.id, partner_id=self.analytic_id.subscriber_id.id)
                accessory_line = accessory_line.get('value', {})
                compl_line = {
                    'product_id': access_id.id,
                    'quantity': 1,
                }
                accessory_line.update(compl_line)
                invoice_line.append((0, 0, accessory_line))
            default_account = self.env['account.account'].search([('code', '=', '410000')])
            ctx_vals = {
                'default_name': self.name,
                'default_state': 'draft',
                'default_type': 'out_invoice',
                'default_history_id': self.id,
                'default_analytic_id': self.analytic_id.id,
                'default_prm_datedeb': dt.strftime(dt.strptime(self.starting_date, DEFAULT_SERVER_DATE_FORMAT), DEFAULT_SERVER_DATE_FORMAT),
                'default_prm_datefin': dt.strftime(dt.strptime(self.ending_date, DEFAULT_SERVER_DATE_FORMAT), DEFAULT_SERVER_DATE_FORMAT),
                'default_date_invoice': dt.strftime(dt.now(), DEFAULT_SERVER_DATE_FORMAT),
                'default_partner_id': self.analytic_id.subscriber_id.id,
                'default_final_customer_id': self.analytic_id.subscriber_id.id,
                'default_origin': self.analytic_id.name +'/'+self.name,
                'default_pol_numpol': self.analytic_id.name,
                'default_journal_id': self._get_user_journal().id,
                'default_account_id': self.analytic_id.subscriber_id.property_account_receivable.id or default_account.id,
                'default_invoice_line': invoice_line,
                'default_comment': self.comment,
            }
            ctx = self._context.copy()
            ctx.update(ctx_vals)
            res.update({
                'type': 'ir.actions.act_window',
                'name': _('Invoice'),
                'res_model': 'account.invoice',
                'view_type': 'form',
                'view_mode': 'form',
                'view_id': [self.env.ref('account.invoice_form').id],
                'context': ctx,
                'target': 'current',
                'flags': {'form': {'action_buttons': True, 'options': {'mode': 'edit'}}},
            })
        return res

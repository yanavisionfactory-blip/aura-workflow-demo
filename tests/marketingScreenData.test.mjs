import test from 'node:test';
import assert from 'node:assert/strict';
import { nativeDiscoveryRows, marketingPeriodRows, sourcePurchaseCpa } from '../src/lib/marketingScreenData.mjs';

test('native screen rows preserve actual discovery shape and do not invent performance', () => {
  const accounts=[{label:'Available account',value:'sample-id'}];
  const audiences=[{name:'Available audience',stats:{member_count:1}}];
  assert.deepEqual(nativeDiscoveryRows({ret:accounts,os:[]},'google'),accounts);
  assert.deepEqual(nativeDiscoveryRows({lists:audiences},'mailchimp'),audiences);
  assert.deepEqual(nativeDiscoveryRows({ret:{lists:audiences}},'mailchimp'),audiences);
  assert.deepEqual(nativeDiscoveryRows({error:'Unavailable',ret:accounts},'google'),[]);
  assert.deepEqual(nativeDiscoveryRows(undefined,'mailchimp'),[]);
  assert.deepEqual(nativeDiscoveryRows({campaigns:[{spend:100}]},'google'),[]);
});

test('campaign table filters stay within the selected source week and handle zero purchases', () => {
  const packet={rows:[{period:'current',campaign:'Coffee video',spend:400,purchases:13},
    {period:'previous',campaign:'Coffee video',spend:400,purchases:16},
    {period:'current',campaign:'House Blend static',spend:550,purchases:6}]};
  assert.deepEqual(marketingPeriodRows(packet,'current','VIDEO'),[packet.rows[0]]);
  assert.deepEqual(marketingPeriodRows(packet,'previous'),[packet.rows[1]]);
  assert.equal(sourcePurchaseCpa(packet.rows[0]),400/13);
  assert.equal(sourcePurchaseCpa({spend:100,purchases:0}),null);
});

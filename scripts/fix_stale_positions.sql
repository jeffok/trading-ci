-- 修复数据库中的无效持仓 - SQL 版本
-- 
-- 使用方法：
--   1. 查看当前 OPEN 持仓：
--      psql -U postgres -d trading-ci -f scripts/fix_stale_positions.sql
--
--   2. 清理所有 OPEN 持仓（谨慎使用）：
--      psql -U postgres -d trading-ci -c "UPDATE positions SET status='CLOSED', updated_at=now(), closed_at_ms=extract(epoch from now())::bigint * 1000, exit_reason='MANUAL_CLEANUP' WHERE status='OPEN';"

-- 1. 查看当前 OPEN 持仓
SELECT 
    position_id,
    idempotency_key,
    symbol,
    timeframe,
    side,
    qty_total,
    entry_price,
    status,
    opened_at_ms,
    created_at,
    updated_at
FROM positions
WHERE status = 'OPEN'
ORDER BY created_at DESC;

-- 2. 统计 OPEN 持仓数量
SELECT 
    COUNT(*) as open_count,
    COUNT(DISTINCT symbol) as unique_symbols
FROM positions
WHERE status = 'OPEN';

-- 3. 按交易对分组统计
SELECT 
    symbol,
    side,
    COUNT(*) as count,
    SUM(qty_total) as total_qty
FROM positions
WHERE status = 'OPEN'
GROUP BY symbol, side
ORDER BY symbol, side;

-- 4. 清理所有 OPEN 持仓（取消注释以执行）
-- UPDATE positions
-- SET 
--     status = 'CLOSED',
--     updated_at = now(),
--     closed_at_ms = extract(epoch from now())::bigint * 1000,
--     exit_reason = 'MANUAL_CLEANUP'
-- WHERE status = 'OPEN';

-- 5. 清理特定交易对的 OPEN 持仓（取消注释并修改 symbol）
-- UPDATE positions
-- SET 
--     status = 'CLOSED',
--     updated_at = now(),
--     closed_at_ms = extract(epoch from now())::bigint * 1000,
--     exit_reason = 'MANUAL_CLEANUP'
-- WHERE status = 'OPEN' AND symbol = 'BTCUSDT';

-- 6. 清理特定 idempotency_key 的持仓（取消注释并修改 idempotency_key）
-- UPDATE positions
-- SET 
--     status = 'CLOSED',
--     updated_at = now(),
--     closed_at_ms = extract(epoch from now())::bigint * 1000,
--     exit_reason = 'MANUAL_CLEANUP'
-- WHERE status = 'OPEN' AND idempotency_key = 'your_idempotency_key_here';

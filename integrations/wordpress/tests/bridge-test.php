<?php
// Dependency-free contract tests. Vendor methods are boundary doubles; these
// tests verify authentication, delegation, write restrictions and read-back.
namespace {
    define( 'ABSPATH', __DIR__ );
    define( 'RANK_MATH_VERSION', '1.0.280' );
    define( 'IMAGIFY_VERSION', '2.3.4' );
    $GLOBALS['authorized'] = true;
    $GLOBALS['vendor_allowed'] = true;
    $GLOBALS['calls'] = array();
    $GLOBALS['meta'] = array();
    $GLOBALS['status'] = 'unoptimized';
    $GLOBALS['posts'] = array(
        107 => (object) array( 'ID' => 107, 'post_type' => 'post', 'post_status' => 'draft' ),
        200 => (object) array( 'ID' => 200, 'post_type' => 'post', 'post_status' => 'publish' ),
        300 => (object) array( 'ID' => 300, 'post_type' => 'attachment', 'post_status' => 'inherit' ),
    );
    class WP_Error {
        public $code;
        public function __construct( $code, $message = '', $data = array() ) { $this->code = $code; }
    }
    class WP_REST_Request {
        public $params = array();
        public function __construct( $method, $route ) { $GLOBALS['calls'][] = $route; }
        public function set_param( $key, $value ) { $this->params[$key] = $value; }
    }
    class Imagify_Requirements { public static function is_api_key_valid() { return true; } }
    function add_action( $name, $callback ) {}
    function register_rest_route( $namespace, $route, $definition ) { $GLOBALS['routes'][$route] = $definition; }
    function is_user_logged_in() { return $GLOBALS['authorized']; }
    function current_user_can( $capability, $id = null ) { return $GLOBALS['authorized']; }
    function is_wp_error( $value ) { return $value instanceof WP_Error; }
    function absint( $value ) { return abs( (int) $value ); }
    function get_post( $id ) { return $GLOBALS['posts'][$id] ?? null; }
    function get_post_status( $id ) { return $GLOBALS['posts'][$id]->post_status; }
    function get_post_meta( $id, $key, $single ) { return $GLOBALS['meta'][$id][$key] ?? ''; }
    function sanitize_text_field( $value ) { return trim( strip_tags( $value ) ); }
    function get_imagify_option( $key ) { return 'never-return-this-test-key'; }
    function get_bloginfo( $field ) { return '6.8.1'; }
    function rest_do_request( $request ) {
        $GLOBALS['writes'] = ( $GLOBALS['writes'] ?? 0 ) + 1;
        if ( empty( $GLOBALS['discard_write'] ) ) {
            $GLOBALS['meta'][$request->params['objectID']] = $request->params['meta'];
        }
        return new class { public function is_error() { return false; } };
    }
    function check( $condition, $label ) {
        if ( ! $condition ) { throw new \RuntimeException( 'Failed: ' . $label ); }
        $GLOBALS['assertions'] = ( $GLOBALS['assertions'] ?? 0 ) + 1;
    }
}
namespace RankMath\Abilities\Post_SEO {
    class Get_Post_SEO_Meta {
        public function __construct( $category, $meta ) {}
        public function check_permissions() { return $GLOBALS['vendor_allowed']; }
        public function execute( $input ) { $GLOBALS['calls'][] = 'rankmath-reader'; return array( 'post_id' => $input['post_id'] ); }
    }
}
namespace RankMath\Abilities\Content_Analysis {
    class Analyze_Post_Content extends \RankMath\Abilities\Post_SEO\Get_Post_SEO_Meta {}
}
namespace RankMath\Rest { class Shared {} }
namespace Imagify\Abilities {
    class GetStats {
        public function check_permissions() { return $GLOBALS['vendor_allowed']; }
        public function execute() { $GLOBALS['calls'][] = 'imagify-stats'; return array( 'wp' => array( 'count_optimized' => 1 ) ); }
    }
    class GetMediaStatus extends GetStats {
        public function execute( $input = array() ) { return array( 'status' => $GLOBALS['status'], 'optimized_size' => 'success' === $GLOBALS['status'] ? 12 : 0 ); }
    }
    class OptimizeMedia extends GetStats {
        public function execute( $input = array() ) {
            $GLOBALS['optimize_input'] = $input;
            return array( 'status' => true === ( $input['confirm'] ?? null ) ? 'success' : 'confirmation_required' );
        }
    }
}
namespace {
    require __DIR__ . '/../aura-seo-bridge/aura-seo-bridge.php';
    Aura_SEO_Bridge::register();
    check( count( $GLOBALS['routes'] ) === 7, 'fixed routes only' );
    foreach ( $GLOBALS['routes'] as $route ) {
        check( $route['permission_callback'] === array( 'Aura_SEO_Bridge', 'authorized' ), 'all routes authenticated' );
    }
    $status = Aura_SEO_Bridge::status();
    check( count( $status['plugins']['rankmath']['operations'] ) === 3, 'RankMath contract' );
    check( count( $status['plugins']['imagify']['operations'] ) === 3, 'Imagify contract' );
    check( false === strpos( json_encode( $status ), 'never-return-this-test-key' ), 'no secret in status' );
    $GLOBALS['authorized'] = false;
    check( ! Aura_SEO_Bridge::authorized(), 'anonymous denied' );
    check( is_wp_error( Aura_SEO_Bridge::execute( 'imagify.stats.get', array() ) ), 'direct anonymous call denied' );
    $GLOBALS['authorized'] = true;
    $GLOBALS['vendor_allowed'] = false;
    check( is_wp_error( Aura_SEO_Bridge::execute( 'imagify.stats.get', array() ) ), 'native plugin permission preserved' );
    check( ! in_array( 'imagify-stats', $GLOBALS['calls'], true ), 'denied operation not invoked' );
    $GLOBALS['vendor_allowed'] = true;
    check( Aura_SEO_Bridge::execute( 'imagify.stats.get', array() )['wp']['count_optimized'] === 1, 'vendor stats returned' );
    check( is_wp_error( Aura_SEO_Bridge::execute( 'imagify.media_status.get', array( 'media_id' => 107 ) ) ), 'only attachments accepted' );
    $input = array( 'post_id' => 200, 'title' => 'Demo title', 'description' => 'Demo description', 'focus_keyword' => 'AC repair Dallas' );
    check( Aura_SEO_Bridge::execute( 'rankmath.post_seo.update', $input )->code === 'aura_draft_only', 'published posts cannot be changed' );
    check( empty( $GLOBALS['writes'] ), 'published rejection performs no write' );
    $input['post_id'] = 107;
    $result = Aura_SEO_Bridge::execute( 'rankmath.post_seo.update', $input );
    check( $result['verified'] && $result['post_status'] === 'draft', 'saved values verified and still draft' );
    check( $result['saved_fields']['rank_math_description'] === 'Demo description', 'exact metadata read back' );
    check( in_array( '/rankmath/v1/updateMeta', $GLOBALS['calls'], true ), 'native RankMath update route used' );
    check( $GLOBALS['writes'] === 1, 'one write' );
    $result = Aura_SEO_Bridge::execute( 'rankmath.post_seo.update', $input );
    check( $result['reused'] && $GLOBALS['writes'] === 1, 'successful write is not repeated' );
    $GLOBALS['discard_write'] = true;
    $input['title'] = 'Changed title';
    check( Aura_SEO_Bridge::execute( 'rankmath.post_seo.update', $input )->code === 'aura_metadata_unverified', 'failed read-back cannot claim success' );
    $preview = Aura_SEO_Bridge::execute( 'imagify.media.optimize', array( 'media_id' => 300 ) );
    check( $preview['status'] === 'confirmation_required', 'quota confirmation preview preserved' );
    check( ! isset( $GLOBALS['optimize_input']['confirm'] ), 'bridge never inserts confirmation' );
    $result = Aura_SEO_Bridge::execute( 'imagify.media.optimize', array( 'media_id' => 300, 'confirm' => true ) );
    check( $result['status'] === 'queued' && ! $result['completed'], 'queued job is not reported complete' );
    $GLOBALS['status'] = 'success';
    unset( $GLOBALS['optimize_input'] );
    $result = Aura_SEO_Bridge::execute( 'imagify.media.optimize', array( 'media_id' => 300, 'confirm' => true ) );
    check( $result['reused'] && ! isset( $GLOBALS['optimize_input'] ), 'existing successful optimization reused' );
    check( is_wp_error( Aura_SEO_Bridge::execute( 'arbitrary.function', array() ) ), 'unknown methods denied' );
    echo 'WordPress bridge: ' . $GLOBALS['assertions'] . " assertions passed\n";
}

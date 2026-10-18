<?php
/**
 * Plugin Name: AURA SEO Bridge
 * Description: Authenticated access to installed RankMath and Imagify operations using existing WordPress application passwords. No new keys, public data routes, or core changes.
 * Version: 1.0.0
 * Requires at least: 6.3
 * Requires PHP: 7.4
 * Author: AURA
 * License: GPL-2.0-or-later
 */

defined( 'ABSPATH' ) || exit;

final class Aura_SEO_Bridge {
    const VERSION = '1.0.0';

    private static function operations() {
        return array(
            'rankmath.post_seo.get' => array( 'rankmath', '\\RankMath\\Abilities\\Post_SEO\\Get_Post_SEO_Meta' ),
            'rankmath.post_analysis.get' => array( 'rankmath', '\\RankMath\\Abilities\\Content_Analysis\\Analyze_Post_Content' ),
            'rankmath.post_seo.update' => array( 'rankmath', '\\RankMath\\Abilities\\Post_SEO\\Get_Post_SEO_Meta' ),
            'imagify.stats.get' => array( 'imagify', '\\Imagify\\Abilities\\GetStats' ),
            'imagify.media_status.get' => array( 'imagify', '\\Imagify\\Abilities\\GetMediaStatus' ),
            'imagify.media.optimize' => array( 'imagify', '\\Imagify\\Abilities\\OptimizeMedia' ),
        );
    }

    public static function register() {
        register_rest_route( 'aura-seo/v1', '/status', array(
            'methods' => 'GET', 'callback' => array( __CLASS__, 'status' ),
            'permission_callback' => array( __CLASS__, 'authorized' ),
        ) );
        foreach ( self::operations() as $operation => $definition ) {
            $args = array();
            if ( 'rankmath' === $definition[0] ) {
                $args['post_id'] = array( 'type' => 'integer', 'minimum' => 1, 'required' => true );
            } elseif ( 'imagify.stats.get' !== $operation ) {
                $args['media_id'] = array( 'type' => 'integer', 'minimum' => 1, 'required' => true );
            }
            if ( 'rankmath.post_seo.update' === $operation ) {
                foreach ( array( 'title' => 200, 'description' => 500, 'focus_keyword' => 300 ) as $key => $limit ) {
                    $args[$key] = array( 'type' => 'string', 'maxLength' => $limit, 'required' => true );
                }
            }
            if ( 'imagify.media.optimize' === $operation ) {
                $args['optimization_level'] = array( 'type' => 'integer', 'minimum' => 0, 'maximum' => 2 );
                $args['confirm'] = array( 'type' => 'boolean', 'default' => false );
            }
            register_rest_route( 'aura-seo/v1', '/' . $definition[0] . '/' . preg_quote( $operation, '/' ), array(
                'methods' => 'POST',
                'callback' => static function ( $request ) use ( $operation, $args ) {
                    $input = $request->get_json_params();
                    if ( null === $input ) {
                        $input = array();
                    }
                    if ( ! is_array( $input ) || array_diff( array_keys( $input ), array_keys( $args ) ) ) {
                        return new WP_Error( 'aura_invalid_input', 'Unexpected operation arguments.', array( 'status' => 400 ) );
                    }
                    return self::execute( $operation, $input );
                },
                'permission_callback' => array( __CLASS__, 'authorized' ),
                'args' => $args,
            ) );
        }
    }

    public static function authorized() {
        // WordPress core authenticates the existing application password. This
        // plugin never creates credentials or permits anonymous execution.
        return is_user_logged_in() && current_user_can( 'manage_options' );
    }

    public static function status() {
        $plugins = array(
            'rankmath' => array( 'version' => defined( 'RANK_MATH_VERSION' ) ? RANK_MATH_VERSION : '', 'operations' => array() ),
            'imagify' => array( 'version' => defined( 'IMAGIFY_VERSION' ) ? IMAGIFY_VERSION : '', 'operations' => array(),
                'api_key_configured' => function_exists( 'get_imagify_option' ) && (bool) get_imagify_option( 'api_key' ),
                'api_key_valid' => class_exists( 'Imagify_Requirements' ) && Imagify_Requirements::is_api_key_valid() ),
        );
        foreach ( self::operations() as $operation => $definition ) {
            if ( $plugins[$definition[0]]['version'] && class_exists( $definition[1] ) ) {
                if ( 'rankmath.post_seo.update' === $operation && ! class_exists( '\\RankMath\\Rest\\Shared' ) ) {
                    continue;
                }
                $plugins[$definition[0]]['operations'][] = $operation;
            }
        }
        return array( 'bridge_version' => self::VERSION, 'wordpress_version' => get_bloginfo( 'version' ), 'plugins' => $plugins );
    }

    private static function ability( $operation ) {
        $operations = self::operations();
        if ( ! isset( $operations[$operation] ) || ! class_exists( $operations[$operation][1] ) ) {
            return new WP_Error( 'aura_plugin_unavailable', 'The installed plugin does not provide this operation.', array( 'status' => 409 ) );
        }
        $class = $operations[$operation][1];
        $ability = 'rankmath' === $operations[$operation][0] ? new $class( 'aura', array() ) : new $class();
        if ( ! $ability->check_permissions() ) {
            return new WP_Error( 'aura_plugin_forbidden', 'The plugin denied this operation.', array( 'status' => 403 ) );
        }
        return $ability;
    }

    public static function execute( $operation, array $input ) {
        if ( ! self::authorized() ) {
            return new WP_Error( 'aura_forbidden', 'Authentication and site management permission are required.', array( 'status' => 403 ) );
        }
        try {
            $ability = self::ability( $operation );
            if ( is_wp_error( $ability ) ) {
                return $ability;
            }
            if ( 0 === strpos( $operation, 'rankmath.' ) ) {
                $post_id = isset( $input['post_id'] ) ? absint( $input['post_id'] ) : 0;
                $post = get_post( $post_id );
                if ( ! $post || ! current_user_can( 'edit_post', $post_id ) ) {
                    return new WP_Error( 'aura_post_forbidden', 'This post is not accessible.', array( 'status' => 403 ) );
                }
                if ( 'rankmath.post_seo.update' === $operation ) {
                    return self::update_rankmath( $ability, $post, $input );
                }
                return $ability->execute( array( 'post_id' => $post_id ) );
            }
            if ( 'imagify.stats.get' === $operation ) {
                return $ability->execute();
            }
            $media_id = isset( $input['media_id'] ) ? absint( $input['media_id'] ) : 0;
            $post = get_post( $media_id );
            if ( ! $post || 'attachment' !== $post->post_type || ! current_user_can( 'edit_post', $media_id ) ) {
                return new WP_Error( 'aura_media_forbidden', 'This media attachment is not accessible.', array( 'status' => 403 ) );
            }
            if ( 'imagify.media_status.get' === $operation ) {
                return $ability->execute( array( 'media_id' => $media_id ) );
            }
            $status_ability = self::ability( 'imagify.media_status.get' );
            if ( is_wp_error( $status_ability ) ) {
                return $status_ability;
            }
            $before = $status_ability->execute( array( 'media_id' => $media_id ) );
            if ( isset( $before['status'] ) && 'success' === $before['status'] ) {
                return array( 'status' => 'already_optimized', 'completed' => true, 'reused' => true, 'media_status' => $before );
            }
            // Preserve the vendor's API-key, quota and confirm checks. Never
            // turn a preview into a write automatically or buy additional quota.
            $result = $ability->execute( $input );
            if ( ! isset( $result['status'] ) || 'success' !== $result['status'] ) {
                return $result;
            }
            $after = $status_ability->execute( array( 'media_id' => $media_id ) );
            $complete = isset( $after['status'], $after['optimized_size'] ) && 'success' === $after['status'] && $after['optimized_size'] > 0;
            return array( 'status' => $complete ? 'completed' : 'queued', 'completed' => $complete,
                'optimization' => $result, 'media_status' => $after );
        } catch ( Throwable $error ) {
            // No exception messages, server paths, API keys or stack traces in
            // REST responses. The WordPress administrator can inspect plugin logs.
            return new WP_Error( 'aura_plugin_failed', 'The plugin could not complete this request.', array( 'status' => 502 ) );
        }
    }

    private static function update_rankmath( $reader, $post, array $input ) {
        if ( ! in_array( $post->post_status, array( 'draft', 'pending', 'private' ), true ) ) {
            return new WP_Error( 'aura_draft_only', 'Metadata updates are restricted to unpublished posts.', array( 'status' => 409 ) );
        }
        $meta = array();
        foreach ( array( 'title', 'description', 'focus_keyword' ) as $key ) {
            if ( ! isset( $input[$key] ) || ! is_string( $input[$key] ) ) {
                return new WP_Error( 'aura_invalid_input', 'All three SEO fields are required.', array( 'status' => 400 ) );
            }
            $meta['rank_math_' . $key] = sanitize_text_field( $input[$key] );
        }
        $reused = true;
        foreach ( $meta as $key => $value ) {
            if ( (string) get_post_meta( $post->ID, $key, true ) !== $value ) {
                $reused = false;
            }
        }
        if ( ! $reused ) {
            $request = new WP_REST_Request( 'POST', '/rankmath/v1/updateMeta' );
            $request->set_param( 'objectID', $post->ID );
            $request->set_param( 'objectType', 'post' );
            $request->set_param( 'meta', $meta );
            // RankMath's registered route enforces its own object permissions
            // and sanitization. Do not bypass those callbacks with direct writes.
            $response = rest_do_request( $request );
            if ( $response->is_error() ) {
                return new WP_Error( 'aura_metadata_failed', 'RankMath did not accept the metadata update.', array( 'status' => 502 ) );
            }
        }
        $saved = array();
        foreach ( $meta as $key => $value ) {
            $saved[$key] = (string) get_post_meta( $post->ID, $key, true );
            if ( $saved[$key] !== $value ) {
                return new WP_Error( 'aura_metadata_unverified', 'The saved RankMath fields did not match the requested values.', array( 'status' => 502 ) );
            }
        }
        return array( 'verified' => true, 'reused' => $reused, 'post_id' => $post->ID,
            'post_status' => get_post_status( $post->ID ), 'saved_fields' => $saved,
            'rankmath' => $reader->execute( array( 'post_id' => $post->ID ) ) );
    }
}

add_action( 'rest_api_init', array( 'Aura_SEO_Bridge', 'register' ) );
